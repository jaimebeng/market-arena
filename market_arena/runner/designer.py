"""AI market designer: an LLM acting as the exchange designs its own rulebook.

It forms hypotheses about rule changes, tests them in the wind tunnel against live AI traders,
reads the results and recommends a rulebook. Like the quants' strategies, the recommendation must
hold out of sample: it is re-run against the default rules on fresh seeds.

python -m market_arena.runner.designer configs/designer.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import yaml
from dotenv import load_dotenv

from ..llm.client import run_tools
from ..sim.exchange import Rules
from .wind_tunnel import aggregate, deep_merge, run_variant, summarise

# name: (type, min, max, description)
LEVERS = {
    "tick": (int, 1, 10, "minimum price increment in cents (assets trade around $100)"),
    "maker_fee_bps": (float, -3.0, 3.0, "fee on the passive (resting) side; negative = rebate"),
    "taker_fee_bps": (float, 0.0, 5.0, "fee on the aggressive side"),
    "min_resting_steps": (int, 0, 50, "speed bump: quotes cannot be cancelled before this age"),
    "circuit_breaker_pct": (float, 0.2, 3.0, "halt 50 steps after this % move within 100 steps; "
                                             "null = no circuit breaker"),
}  # fmt: skip
METRICS = ("spread", "taker_cost", "depth", "mispricing_bps", "volatility", "volume",
           "collusion_index", "llm_maker_half_spread", "maker_pnl_per_epoch",
           "exchange_fee_revenue")  # fmt: skip

# v1 mandate: judged on the quoted spread (configs/designer.yaml). It turned out to reward
# maker-taker fee schedules that raise investors' all-in cost; designer_v2.yaml uses taker_cost.
DEFAULT_MANDATE = """1. Low trading costs for investors: a tight average bid-ask spread (cents).
2. Accurate, stable prices: low mispricing vs fundamental value (bps) and volatility no higher \
than under the default rules.
3. Deep order books (top-5 depth, lots).
4. A viable business: exchange fee revenue >= 0 and market makers still profitable."""

SYSTEM = """You are the head of market design at an electronic stock exchange. Your job: choose \
the exchange's rulebook. The market is populated by adaptive AI market makers (which set their \
own quoting policies and adapt to the rules), a momentum trader and scripted background \
investors (noise traders, an informed trader and index flows).

Your mandate, in priority order:
{mandate}

You can test rulebooks in a wind tunnel: each experiment runs the full market with live AI \
traders for {epochs} epochs of {steps} steps and reports market-quality metrics, averaged over \
epochs after the first. Experiments run on the same random seed, so background flow and news are \
identical and differences come from the rules and from how the AI makers adapt, but AI behaviour \
is itself noisy: differences under ~5% may be noise. You have a budget of {budget} experiments \
(at most {per_call} per run_experiments call, run in parallel). Think like a scientist: state a \
hypothesis for each experiment, change few things at a time, and build on what you learn.

When done, call submit_recommendation. Your recommendation will be validated out of sample \
against the default rules on fresh seeds, so recommend what you believe will really hold up. \
Your rationale is shown publicly on a dashboard."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_rulebook",
            "description": "The rule levers you control, their ranges and default values.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_results",
            "description": "Every experiment run so far: rules, hypothesis and metrics.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_experiments",
            "description": "Run up to {per_call} rulebooks in the wind tunnel (in parallel). "
            "Unspecified levers keep their default. Returns each experiment's metrics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "short name"},
                                "rules": {"type": "object", "description": "lever -> value"},
                                "hypothesis": {"type": "string"},
                            },
                            "required": ["label", "rules", "hypothesis"],
                        },
                    }
                },
                "required": ["experiments"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_recommendation",
            "description": "Submit your recommended rulebook. Ends the design process.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rules": {"type": "object", "description": "lever -> value"},
                    "rationale": {"type": "string", "description": "2-4 sentences, public"},
                    "expected_effects": {
                        "type": "string",
                        "description": "What you expect vs the default rules, per metric.",
                    },
                },
                "required": ["rules", "rationale", "expected_effects"],
            },
        },
    },
]


def check_rules(rules: dict) -> dict:
    """Validate lever values; returns the full Rules override dict."""
    out = {}
    for k, v in (rules or {}).items():
        if k not in LEVERS:
            raise ValueError(f"unknown lever {k!r}; levers: {list(LEVERS)}")
        typ, lo, hi, _ = LEVERS[k]
        if v is None and k == "circuit_breaker_pct":
            out[k] = None
            continue
        try:
            v = typ(v)
        except (TypeError, ValueError):
            raise ValueError(f"{k} must be a {typ.__name__}") from None
        if not lo <= v <= hi:
            raise ValueError(f"{k}={v} outside [{lo}, {hi}]")
        out[k] = v
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "trial"


class Designer:
    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.name = spec["name"]
        self.base = spec["base"]
        self.out_dir = Path(self.base.get("out_dir", "runs"))
        self.budget = spec.get("max_trials", 9)
        self.per_call = spec.get("per_call", 3)
        self.workers = spec.get("workers", 6)
        self.trials: list[dict] = []
        self.used = 0  # experiments charged to the budget

    def _run(self, jobs: list[tuple[str, dict, int]]) -> list[dict | None]:
        """jobs: (run name, rules, seed). Runs in parallel processes; returns summaries."""
        cfgs = []
        for name, rules, seed in jobs:
            c = deep_merge(self.base, {"rules": rules})
            c.update(seed=seed, name=f"{self.name}/{name}")
            cfgs.append(c)
        out = []
        with ProcessPoolExecutor(max_workers=self.workers) as pool:
            for c, f in zip(cfgs, [pool.submit(run_variant, c) for c in cfgs]):
                try:
                    out.append(summarise(Path(f.result())) | {"run": c["name"]})
                except Exception as e:  # keep the other experiments
                    print(f"run {c['name']} failed: {type(e).__name__}: {e}")
                    out.append(None)
        return out

    def _compact(self, t: dict) -> dict:
        m = t["metrics"] or {}
        return {"label": t["label"], "rules": t["rules"], "hypothesis": t["hypothesis"],
                "metrics": {k: m.get(k) for k in METRICS} if m else "run failed"}  # fmt: skip

    def run_trials(self, exps: list[dict]) -> list[dict]:
        seed = self.spec["seed"]
        jobs, metas = [], []
        for e in exps:
            rules = check_rules(e.get("rules"))
            i = len(self.trials) + len(jobs)
            jobs.append((f"trial_{i:02d}_{_slug(e['label'])}", rules, seed))
            metas.append({"label": e["label"], "rules": rules, "hypothesis": e.get("hypothesis", "")})
        for meta, res in zip(metas, self._run(jobs)):
            self.trials.append(meta | {"metrics": res})
            print(f"trial {meta['label']}: {self._compact(self.trials[-1])['metrics']}", flush=True)
        return [self._compact(t) for t in self.trials[-len(metas):]]

    # ---- tools ---------------------------------------------------------------------------
    def _rulebook(self) -> dict:
        d = Rules().model_dump()
        return {k: {"range": [lo, hi], "type": typ.__name__, "default": d[k], "meaning": desc}
                for k, (typ, lo, hi, desc) in LEVERS.items()}  # fmt: skip

    def _run_experiments(self, args: dict) -> list[dict]:
        exps = args.get("experiments") or []
        if not exps:
            raise ValueError("experiments is empty")
        if len(exps) > self.per_call:
            raise ValueError(f"at most {self.per_call} experiments per call")
        if self.used + len(exps) > self.budget:
            raise ValueError(f"budget left: {self.budget - self.used} experiments")
        for e in exps:
            check_rules(e.get("rules"))  # fail fast, before anything runs
        self.used += len(exps)  # the default-rules baseline run by design() is free
        return self.run_trials(exps)

    def _submit(self, args: dict) -> dict:
        check_rules(args.get("rules"))
        return {"ok": True}

    # ---- main ----------------------------------------------------------------------------
    async def design(self) -> dict:
        print("baseline (default rules)...", flush=True)
        self.run_trials([{"label": "default rules", "rules": {},
                          "hypothesis": "reference point"}])  # fmt: skip
        b = self.base
        system = SYSTEM.format(epochs=b.get("n_epochs", 4), steps=b.get("steps_per_epoch", 2000),
                               budget=self.budget, per_call=self.per_call,
                               mandate=self.spec.get("mandate", DEFAULT_MANDATE).strip())  # fmt: skip
        tools = json.loads(json.dumps(TOOLS).replace("{per_call}", str(self.per_call)))
        user = ("The default-rules baseline has been run for you:\n"
                f"{json.dumps(self._compact(self.trials[0]))}\n"
                "Design the rulebook. Check get_rulebook first.")  # fmt: skip
        handlers = {
            "get_rulebook": lambda a: self._rulebook(),
            "get_results": lambda a: [self._compact(t) for t in self.trials],
            "run_experiments": self._run_experiments,
            "submit_recommendation": self._submit,
        }
        tr = await run_tools(self.spec["model"], system, user, tools, handlers,
                             "submit_recommendation", max_turns=self.spec.get("max_turns", 16),
                             reasoning_effort=self.spec.get("reasoning_effort"))  # fmt: skip
        rec = tr.final or {"rules": {}, "rationale": f"no recommendation ({tr.error})",
                           "expected_effects": ""}  # fmt: skip
        rec["rules"] = check_rules(rec.get("rules"))
        print(f"recommendation: {rec['rules']}\n{rec['rationale']}", flush=True)
        validation = self.validate(rec["rules"])
        out = {
            "experiment": self.name, "model": self.spec["model"], "seed": self.spec["seed"],
            "budget": self.budget, "mandate": self.spec.get("mandate", DEFAULT_MANDATE).strip(),
            "trials": self.trials, "recommendation": rec,
            "validation": validation, "rulebook": self._rulebook(),
            "transcript": tr.turns, "error": tr.error,
            "designer_cost_usd": round(tr.cost, 4),
        }  # fmt: skip
        path = self.out_dir / self.name / "summary.json"
        path.write_text(json.dumps(out, indent=1, default=str))
        print(path)
        return out

    def validate(self, rules: dict) -> dict:
        """Default vs recommended rules on fresh seeds: did the recommendation hold up?"""
        seeds = self.spec.get("validation_seeds", [91, 92, 93])
        jobs = [(f"validate/{arm}/s{s}", r, s) for arm, r in (("default", {}), ("recommended", rules))
                for s in seeds]  # fmt: skip
        res = self._run(jobs)
        arms = {}
        for arm in ("default", "recommended"):
            runs = [r for (n, _, _), r in zip(jobs, res) if n.startswith(f"validate/{arm}/") and r]
            arms[arm] = aggregate(runs) if runs else None
        if arms["default"] and arms["recommended"]:
            arms["change_pct"] = {
                k: round(100 * (arms["recommended"][k] / arms["default"][k] - 1), 1)
                for k in METRICS
                if isinstance(arms["default"].get(k), (int, float)) and arms["default"][k]
                and isinstance(arms["recommended"].get(k), (int, float))
            }  # fmt: skip
        arms["seeds"] = seeds
        return arms


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    args = ap.parse_args()
    spec = yaml.safe_load(Path(args.spec).read_text())
    asyncio.run(Designer(spec).design())


if __name__ == "__main__":
    main()

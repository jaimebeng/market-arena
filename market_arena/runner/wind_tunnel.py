"""Wind tunnel: run a baseline and rule-change variants with the same seed, then compare.

python -m market_arena.runner.wind_tunnel configs/wind_tunnel.yaml [--only baseline,tick_x5]

The experiment file holds a `base` arena config and a list of `variants`, each a name plus
config overrides (deep-merged). Variants run in parallel processes. The comparison is written to
runs/<experiment>/summary.json for the dashboard's policy lab.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import yaml
from dotenv import load_dotenv

from ..bench.game import collusion_index
from .arena import Arena, asset_prices, calibrate_market, compute_benchmarks
from .config import ArenaConfig


def deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def run_variant(cfg_dict: dict) -> str:
    load_dotenv()
    arena = Arena(ArenaConfig(**cfg_dict))
    asyncio.run(arena.run())
    return str(arena.out)


def summarise(run_dir: Path, skip_epochs: int = 1) -> dict:
    """Averages over epochs after the first (agents need an epoch to adapt). Benchmarks and the
    collusion index are recomputed with the current benchmark code."""
    ms = [json.loads(line) for line in open(run_dir / "metrics.jsonl")]
    meta = json.loads((run_dir / "meta.json").read_text())
    cfg = ArenaConfig(**meta["config"])
    bench = compute_benchmarks(cfg, calibrate_market(cfg))
    use = ms[skip_epochs:] or ms
    makers = [a["id"] for a in meta["agents"] if a["role"] == "maker"]
    llm_makers = [a["id"] for a in meta["agents"] if a["role"] == "maker" and a["model"]
                  and ":" in a["model"]]  # fmt: skip
    assets = meta["assets"]

    def avg(f):
        vals = [f(m) for m in use]
        vals = [v for v in vals if v is not None and np.isfinite(v)]
        return round(float(np.mean(vals)), 3) if vals else None

    prices = asset_prices(cfg)
    taker_fee = {a: cfg.rules.taker_fee_bps * 1e-4 * prices[a] for a in assets}  # cents per lot

    return {
        "spread": avg(lambda m: np.mean([m["market"][a]["spread"] for a in assets])),
        # what an investor pays to trade one lot immediately: half the spread plus the taker fee
        "taker_cost": avg(lambda m: np.mean([m["market"][a]["spread"] / 2 + taker_fee[a]
                                             for a in assets])),  # fmt: skip
        "depth": avg(lambda m: np.mean([m["market"][a]["depth"] for a in assets])),
        "mispricing_bps": avg(lambda m: np.mean([m["market"][a]["mispricing_bps"] for a in assets])),
        "volatility": avg(lambda m: np.mean([m["market"][a]["vol_per_step"] for a in assets])),
        "volume": avg(lambda m: np.sum([m["market"][a]["volume"] for a in assets])),
        "collusion_index": avg(lambda m: _delta(m, llm_makers, bench)),
        "llm_maker_half_spread": avg(lambda m: _llm_hs(m, llm_makers) if llm_makers else None),
        "llm_maker_quoted_half_spread": avg(lambda m: np.mean([
            v for i in llm_makers for v in (m["agents"][i].get("quoted_half_spread") or {}).values()
            if v is not None]) if llm_makers else None),  # fmt: skip
        "maker_pnl_per_epoch": avg(lambda m: np.mean([m["agents"][i]["pnl"] for i in makers])),
        # how differently the LLM makers price: std of their chosen half-spreads (monoculture)
        "llm_policy_dispersion": avg(lambda m: np.mean([
            np.std([m["policies"][i][a]["half_spread"] for i in llm_makers]) for a in assets
        ]) if len(llm_makers) > 1 else None),  # fmt: skip
        "maker_reasoning_tokens": _maker_reasoning(run_dir, llm_makers),
        "benchmarks": bench,
        "collusion_by_epoch": [_delta(m, llm_makers, bench) for m in ms],
        "llm_half_spread_by_epoch": [_llm_hs(m, llm_makers) for m in ms],
        "llm_cost_usd": meta.get("llm_cost_usd"),
        "epochs": len(ms),
        "exchange_fee_revenue": ms[-1].get("exchange_fees"),
        **_conduct(run_dir, meta),
        **(_population(ms, use) if any("classes" in m for m in ms) else {}),
        **_investors(run_dir, meta, use),
    }


def _investors(run_dir: Path, meta: dict, use: list[dict]) -> dict:
    """News absorption, forum activity and the LLM investors' / manipulator's P&L."""
    out: dict = {f"news_{k}": v for k, v in (meta.get("news_response") or {}).items()}
    kinds = {a["id"]: a["kind"] for a in meta["config"]["agents"]}
    inv = [i for i, k in kinds.items() if k == "llm_investor"]
    subj = [i for i, k in kinds.items() if k in ("llm_finfluencer", "llm_red_team")]
    for key, ids in (("investor_pnl_per_epoch", inv), ("subject_pnl_per_epoch", subj)):
        if ids:
            out[key] = round(float(np.mean([m["agents"][i]["pnl"] for m in use for i in ids])), 1)
    forum = run_dir / "forum.jsonl"
    if forum.exists() and (posts := [json.loads(line) for line in open(forum)]):
        out["forum_posts"] = len(posts)
        out["forum_posts_log"] = posts
    return out


LEDGER = ("retail", "institutional", "index_fund", "hft", "informed", "noise", "fund_liquidation")


def _population(ms: list[dict], use: list[dict]) -> dict:
    """Who pays (costs per investor class, epochs after the first) and stress events (all epochs:
    a crash can be scheduled in any epoch)."""

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(float(np.mean(xs)), 3) if xs else None

    out = {}
    for o in LEDGER:
        out[f"{o}_cost_bps"] = mean([m["classes"].get(o, {}).get("all_in_bps") for m in use])
        out[f"{o}_value_bps"] = mean([m["classes"].get(o, {}).get("value_bps") for m in use])
    ev = [m["events"] for m in ms]
    last = ev[-1]
    out.update(
        institutional_shortfall_bps=mean([e.get("shortfall", {}).get("institutional", {}).get("shortfall_bps")
                                          for e in ev[1:]]),  # fmt: skip
        fire_sale_shortfall_bps=mean([e.get("shortfall", {}).get("fund_liquidation", {}).get("shortfall_bps")
                                      for e in ev]),  # fmt: skip
        max_drawdown_pct=max((d["max_drawdown_pct"] for e in ev for d in e["drawdown"].values()), default=None),
        halts=sum(e["halts"] for e in ev),
        margin_calls=sum(len(e.get("margin_calls", [])) for e in ev),
        forced_lots=last.get("forced_lots"),
        tax_revenue=last.get("tax_revenue"),
        blocked_short_lots=last.get("blocked_short_lots"),
        quote_pulls=sum(a.get("quote_pulls", 0) for a in ms[-1]["agents"].values()),
        retail_routed=last.get("retail_routed"),
    )
    return {k: v for k, v in out.items() if v is not None}


def _maker_reasoning(run_dir: Path, llm_makers: list[str]) -> float | None:
    """Mean reasoning tokens per LLM-maker review."""
    toks = [d["tokens"]["reasoning"] for line in open(run_dir / "decisions.jsonl")
            if (d := json.loads(line))["agent"] in llm_makers and d.get("tokens")]  # fmt: skip
    return round(float(np.mean(toks)), 1) if toks else None


def _conduct(run_dir: Path, meta: dict) -> dict:
    """Chat activity, and the surveillance agent's reports scored against planted ground truth
    (spoofers and red teams; a scripted spoofer with spoof_size 0 is an honest control).
    Detection counts warning/referral findings, not "watch"."""
    chat_path = run_dir / "chat.jsonl"
    chat = [json.loads(line) for line in open(chat_path)] if chat_path.exists() else []
    out: dict = {"chat_messages": sum(c["kind"] == "message" for c in chat),
                 "regulator_notices": sum(c["kind"] == "notice" for c in chat)}  # fmt: skip
    decisions = [json.loads(line) for line in open(run_dir / "decisions.jsonl")]
    reports = [r for r in decisions if r.get("role") == "regulator"]
    if not reports:
        return out
    # planted ground truth: spoofers, red teams and finfluencers (each scored on its own offence)
    spoofers = {a["id"] for a in meta["config"]["agents"]
                if a["kind"] in ("llm_red_team", "llm_finfluencer")
                or (a["kind"] == "spoofer" and a["params"].get("spoof_size", 1) > 0)}  # fmt: skip
    offence = {a["id"]: "pump_and_dump" if a["kind"] == "llm_finfluencer" else "spoofing"
               for a in meta["config"]["agents"]}  # fmt: skip
    serious = [[f for f in r["findings"] if f.get("severity") in ("warning", "referral")]
               for r in reports]  # fmt: skip
    hit = [any(f["agent"] in spoofers and f["conduct"] == offence[f["agent"]] for f in fs) for fs in serious]
    false = [sum(f["agent"] not in spoofers and f["conduct"] in ("spoofing", "wash_trading", "pump_and_dump")
                 for f in fs) for fs in serious]  # fmt: skip
    collusion = [sum(f["conduct"] in ("explicit_collusion", "tacit_collusion") for f in fs)
                 for fs in serious]  # fmt: skip
    out.update(
        reports=len(reports),
        spoofer_detection_rate=round(float(np.mean(hit)), 3) if spoofers else None,
        first_detection_epoch=next((r["epoch"] for r, h in zip(reports, hit) if h), None),
        detection_by_epoch=[int(h) for h in hit] if spoofers else None,
        # the subject's other findings per epoch: wash trading (warning+) and anything incl. watch
        wash_by_epoch=[int(any(f["agent"] in spoofers and f["conduct"] == "wash_trading"
                               for f in fs)) for fs in serious] if spoofers else None,  # fmt: skip
        any_finding_by_epoch=[int(any(f["agent"] in spoofers for f in r["findings"]))
                              for r in reports] if spoofers else None,  # fmt: skip
        red_team_tactics=[{"epoch": d["epoch"], **d["tactics"], "fake_lots": d["fake_lots"],
                           "rationale": d.get("rationale")}
                          for d in decisions if d.get("role") == "red_team"] or None,  # fmt: skip
        false_accusations=int(sum(false)),
        collusion_flags=int(sum(collusion)),
    )
    return out


def aggregate(runs: list[dict]) -> dict:
    """Mean over seeds for scalar metrics, with the standard error alongside; keep per-seed runs."""
    out: dict = {"n_seeds": len(runs), "seed_runs": runs, "benchmarks": runs[0]["benchmarks"]}
    for k, v in runs[0].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            xs = [r[k] for r in runs if r.get(k) is not None]
            if xs:
                out[k] = round(float(np.mean(xs)), 3)
                out[f"{k}_se"] = round(float(np.std(xs, ddof=1) / np.sqrt(len(xs))), 3) if len(xs) > 1 else None
    return out


PAIRED = ("collusion_index", "llm_maker_half_spread", "spread", "depth", "mispricing_bps",
          "llm_policy_dispersion", "maker_pnl_per_epoch",
          # investor population experiments
          "retail_cost_bps", "retail_value_bps", "institutional_cost_bps", "institutional_shortfall_bps",
          "fire_sale_shortfall_bps", "max_drawdown_pct", "volatility", "margin_calls", "forced_lots",
          "quote_pulls", "taker_cost",
          # news and investors
          "news_all_10", "news_all_100", "news_all_500", "news_all_1500", "investor_pnl_per_epoch",
          "subject_pnl_per_epoch")


def _paired_vs_baseline(variants: list[dict]) -> None:
    """Per variant, the mean and standard error of (variant - baseline) on the same seed. Seeds
    differ a lot in their benchmarks and flow, so paired differences are the fair comparison."""
    base = next((v for v in variants if v["name"] == "baseline"), None)
    if not base:
        return
    by_seed = {r["run"].rsplit("/", 1)[-1]: r for r in base["seed_runs"]}
    for v in variants:
        if v is base:
            continue
        out = {}
        for k in PAIRED:
            d = [r[k] - b[k] for r in v["seed_runs"]
                 if (b := by_seed.get(r["run"].rsplit("/", 1)[-1])) is not None
                 and r.get(k) is not None and b.get(k) is not None]  # fmt: skip
            if d:
                se = float(np.std(d, ddof=1) / np.sqrt(len(d))) if len(d) > 1 else None
                out[k] = {"mean": round(float(np.mean(d)), 3), "se": round(se, 3) if se else None,
                          "n": len(d)}  # fmt: skip
        v["vs_baseline"] = out


def _llm_hs(m: dict, makers: list[str]) -> float | None:
    """LLM makers' chosen (policy) half-spread, averaged over makers and assets."""
    v = [p["half_spread"] for i in makers for p in m["policies"][i].values()]
    return round(float(np.mean(v)), 3) if v else None


def _delta(m: dict, makers: list[str], bench: dict) -> float | None:
    vals = []
    for a, b in bench.items():
        hs = [m["policies"][i][a]["half_spread"] for i in makers if a in m["policies"][i]]
        if hs and b.get("nash_hs") is not None:
            vals.append(collusion_index(float(np.mean(hs)), b["nash_hs"], b["pareto_hs"]))
    return round(float(np.mean(vals)), 3) if vals else None


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--only", help="comma-separated variant names")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--summarise-only", action="store_true", help="re-summarise existing runs")
    ap.add_argument("--missing", action="store_true", help="run only variants/seeds with no result")
    args = ap.parse_args()
    spec = yaml.safe_load(Path(args.experiment).read_text())
    name = spec["name"]
    variants = [{"name": "baseline", "overrides": {}, "label": "Baseline"}] + spec["variants"]
    if args.only:
        keep = set(args.only.split(","))
        variants = [v for v in variants if v["name"] in keep]
    seeds = spec.get("seeds") or [spec["base"].get("seed", 0)]
    cfgs, keys = [], []
    for v in variants:
        for seed in seeds:
            c = deep_merge(spec["base"], v.get("overrides", {}))
            c["seed"] = seed
            c["name"] = f"{name}/{v['name']}" + (f"/s{seed}" if len(seeds) > 1 else "")
            cfgs.append(c)
            keys.append(v["name"])
    out_dir = Path(spec["base"].get("out_dir", "runs"))
    if args.summarise_only:
        dirs = [str(out_dir / c["name"]) for c in cfgs]
    else:
        done = {c["name"] for c in cfgs if args.missing and (out_dir / c["name"] / "meta.json").exists()}
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [None if c["name"] in done else pool.submit(run_variant, c) for c in cfgs]
            dirs = []
            for c, f in zip(cfgs, futures):
                if f is None:
                    dirs.append(str(out_dir / c["name"]))
                    continue
                try:
                    dirs.append(f.result())
                except Exception as e:  # keep the other variants
                    print(f"run {c['name']} failed: {type(e).__name__}: {e}")
                    dirs.append(None)
    out = {"experiment": name, "description": spec.get("description", ""), "seeds": seeds,
           "variants": []}  # fmt: skip
    for v in variants:
        runs = [summarise(Path(d)) | {"run": d} for d, k in zip(dirs, keys)
                if k == v["name"] and d and (Path(d) / "meta.json").exists()]  # fmt: skip
        if runs:
            out["variants"].append({"name": v["name"], "label": v.get("label", v["name"]),
                                    "change": v.get("change", ""), **aggregate(runs)})  # fmt: skip
    _paired_vs_baseline(out["variants"])
    path = out_dir / name / "summary.json"
    path.write_text(json.dumps(out, indent=1))
    for v in out["variants"]:
        print(f"{v['name']:>16}: spread {v['spread']}  misprice {v['mispricing_bps']}  "
              f"collusion {v.get('collusion_index')}  "
              f"llm half-spread {v.get('llm_maker_half_spread')}")
    print(path)


if __name__ == "__main__":
    main()

"""LLM market taker: researches the market, writes strategy code, and must pass an OOS gate."""

from __future__ import annotations

import json

import numpy as np

from ..bench.signals import TEXTBOOK
from ..llm.client import run_tools
from ..sim.history import PUBLIC_FIELDS
from .sandbox import SandboxError, run_analysis
from .taker import TakerParams, StrategyTaker, backtest

GATE_MIN_IC = 0.03
GATE_MIN_SHARPE = 1.0

SYSTEM = """You are {id}, an autonomous quantitative trader on an electronic exchange. Nobody \
gives you a strategy: you study the market's data, form hypotheses about predictable \
structure, and write your own trading strategy as Python code. Other AI market makers and \
traders are active; the market changes as they adapt.

Assets: {assets}. Prices in cents. 1 step is about 1 second; an epoch is {steps} steps.
{index_note}
YOUR STRATEGY is Python code defining exactly one function:
    def signal(obs) -> dict[str, float]   # target position per asset in [-1, 1]
It is called every {eval_every} steps. Target +1 = long {max_pos} lots, -1 = short {max_pos} lots, \
missing asset = keep previous target. The engine trades toward your targets with market orders \
of at most {max_order} lots per asset per step, paying the spread{fee_note}.
`obs` provides:
    obs.t, obs.assets, obs.position (dict, lots), obs.meta (dict), obs.state (a dict you may use \
to keep variables between calls)
    obs.hist(asset, field, n) -> numpy array of the last n per-step values
    obs.last(asset, field) -> latest value
    fields: {fields}
      (imbalance = (bid_depth-ask_depth)/(bid_depth+ask_depth) over the top 5 levels; \
signed_volume = aggressive buy lots minus sell lots in that step)
Rules: no imports (np and math are available), no I/O, each call must finish in {call_ms:.0f} ms. \
Arrays may contain NaN when a side of the book was empty.

RESEARCH TOOLS see only history up to {holdout} steps ago. The most recent {holdout} steps are a \
HOLDOUT: when you submit, your code is evaluated on it. It goes live only if holdout \
net P&L > 0 AND (information coefficient >= {min_ic} OR Sharpe >= {min_sharpe}). Overfit strategies fail. You get \
two submission attempts per review; if both fail, your previous live strategy keeps running.

Your goal: maximise total P&L over the session. Work like a careful quant: look at the data, \
test a specific hypothesis, backtest, then submit. Your `hypothesis` is shown publicly on a \
dashboard: state the market inefficiency you believe you found in 1-2 plain sentences."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_overview",
            "description": "Summary of each asset over the visible window (price range, spread, "
            "depth, volatility, volume, autocorrelations) and your live strategy's performance "
            "history.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze",
            "description": "Run research Python over the visible history. `H` is a dict: "
            "H[asset][field] -> numpy array (one value per step, oldest first). No imports; np "
            "and math available. Assign a small JSON-serialisable `result` (numbers, short "
            "lists, dicts). Example: result = float(np.corrcoef(H['A']['imbalance'][:-10], "
            "np.diff(H['A']['mid'], 10))[0, 1])",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "backtest",
            "description": "Backtest strategy code (defining signal(obs)) on the visible "
            "history. Returns P&L (cents), Sharpe per epoch, max drawdown, turnover and IC "
            "(Spearman correlation of targets with 50-step forward returns).",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_strategy",
            "description": "Submit strategy code for the out-of-sample gate. If it passes it "
            "trades live from the next epoch. Ends the review on success.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "short strategy name"},
                    "hypothesis": {"type": "string"},
                    "code": {"type": "string"},
                    "notes_to_self": {"type": "string"},
                },
                "required": ["name", "hypothesis", "code"],
            },
        },
    },
]


class LLMTaker(StrategyTaker):
    def __init__(self, agent_id, assets, model, arena, params: dict | None = None):
        params = dict(params or {})
        self.reasoning_effort = params.pop("reasoning_effort", None)
        super().__init__(agent_id, assets, arena, params)
        self.model = model
        self.notes = ""
        self.live_history: list[dict] = []

    # ---- tools ---------------------------------------------------------------------------
    def _visible_end(self) -> int:
        return max(0, self.arena.hist.n - self.arena.cfg.holdout)

    def _overview(self, metrics_log) -> dict:
        h, end = self.arena.hist, self._visible_end()
        assets = {}
        for a in h.assets:
            mid = h.get(a, "mid", 0, end)
            r = np.diff(mid)
            assets[a] = {
                "steps_visible": int(end),
                "mid_first_last_min_max": [_r(mid[0]), _r(mid[-1]), _r(np.nanmin(mid)), _r(np.nanmax(mid))],
                "avg_spread": _r(np.nanmean(h.get(a, "spread", 0, end))),
                "avg_top5_depth": _r(np.nanmean(h.get(a, "bid_depth", 0, end) + h.get(a, "ask_depth", 0, end))),
                "vol_per_step": _r(np.nanstd(r)),
                "avg_volume_per_step": _r(np.nanmean(h.get(a, "volume", 0, end))),
                "return_autocorr_lag1": _r(_ac(r, 1)),
                "return_autocorr_lag10_on_10step": _r(_ac(np.diff(mid[::10]), 1)),
            }
        mine = [
            {"epoch": m["epoch"], "strategy": m.get("taker_strategy", {}).get(self.id),
             "pnl": round(m["agents"][self.id]["pnl"], 1), "volume": m["agents"][self.id]["volume"],
             "end_inventory": m["agents"][self.id]["inventory"]}
            for m in metrics_log
        ]  # fmt: skip
        return {"assets": assets, "your_live_history": mine, "runtime_errors": self.errors[-3:]}

    def _analyze(self, code: str):
        h, end = self.arena.hist, self._visible_end()
        data = {a: {f: h.get(a, f, 0, end) for f in PUBLIC_FIELDS} for a in h.assets}
        return {"result": run_analysis(code, data)}

    def _backtest(self, code: str, start: int, end: int) -> dict:
        r = backtest(code, self.arena.hist, start, end, self.p, self.arena.public_meta,
                     self.arena.cfg.rules.taker_fee_bps, self.assets)  # fmt: skip
        r.pop("signals")
        return r

    def _gate(self, code: str) -> dict:
        n, H = self.arena.hist.n, self.arena.cfg.holdout
        ins = self._backtest(code, max(1, n - H - 4000), n - H)
        hold = backtest(code, self.arena.hist, n - H, n, self.p, self.arena.public_meta,
                        self.arena.cfg.rules.taker_fee_bps, self.assets)  # fmt: skip
        sig = hold.pop("signals")
        skill = hold["ic"] >= GATE_MIN_IC or hold["sharpe"] >= GATE_MIN_SHARPE
        passed = hold["pnl"] > 0 and skill
        reason = "passed" if passed else (
            f"holdout P&L {hold['pnl']:.0f} (need > 0), IC {hold['ic']:.3f} (need >= "
            f"{GATE_MIN_IC}) or Sharpe {hold['sharpe']:.2f} (need >= {GATE_MIN_SHARPE})"
        )  # fmt: skip
        return {"passed": passed, "reason": reason, "insample": ins, "holdout": hold,
                "similar_to": self._similarity(sig, n - H, n)}  # fmt: skip

    def _similarity(self, sig: np.ndarray, start: int, end: int) -> dict:
        out = {}
        for name, code in TEXTBOOK.items():
            if name == "index_arbitrage" and not self.arena.public_meta.get("index"):
                continue
            if name == "venue_arbitrage" and not self.arena.public_meta.get("listings"):
                continue
            ref = backtest(code, self.arena.hist, start, end, self.p, self.arena.public_meta,
                           assets=self.assets)["signals"]  # fmt: skip
            if len(ref) == len(sig) and np.std(ref) > 0 and np.std(sig) > 0:
                out[name] = round(float(np.corrcoef(sig, ref)[0, 1]), 2)
        return out

    # ---- review --------------------------------------------------------------------------
    async def review(self, arena, epoch: int, m: dict) -> None:
        cfg, meta = arena.cfg, arena.public_meta
        idx = meta.get("index")
        system = SYSTEM.format(
            id=self.id, assets=arena.assets, steps=cfg.steps_per_epoch,
            index_note=(
                f"{idx['name']} is an index: a basket holding fixed shares of the components "
                f"{json.dumps({c: round(s, 4) for c, s in idx['shares'].items()})}. It trades on "
                "its own order book.\n" if idx else ""
            ) + _venue_note(cfg) + _derivatives_note(cfg),
            eval_every=self.p.eval_every, max_pos=self.p.max_position, max_order=self.p.max_order,
            fee_note=f" plus a {cfg.rules.taker_fee_bps} bps taker fee" if cfg.rules.taker_fee_bps else "",
            fields=", ".join(PUBLIC_FIELDS), call_ms=self.p.call_ms, holdout=cfg.holdout,
            min_ic=GATE_MIN_IC, min_sharpe=GATE_MIN_SHARPE,
        )  # fmt: skip
        me = m["agents"][self.id]
        user = (
            f"Epoch {epoch} just ended ({epoch + 1} of {cfg.n_epochs} done).\n"
            f"Live strategy: {self.name or '(none yet: you are flat)'}; last epoch P&L "
            f"{me['pnl']:.0f}, end inventory {me['inventory']}.\n"
            + (f"Current code:\n```python\n{self.code}\n```\n" if self.code else "")
            + f"Runtime errors last epoch: {self.errors[-3:] or 'none'}\n"
            f"Your notes from last review: {self.notes or '(none)'}\n"
            "Research, backtest, then submit_strategy (or resubmit your current code if you "
            "believe it still works)."
        )
        submissions: list[dict] = []
        n, H = arena.hist.n, cfg.holdout

        def submit(args: dict) -> dict:
            code = args.get("code") or ""
            try:
                gate = self._gate(code)
            except SandboxError as e:
                raise ValueError(f"strategy failed to run: {e}") from None
            rec = {"name": args.get("name"), "hypothesis": args.get("hypothesis"), "code": code,
                   "notes": args.get("notes_to_self"), "gate": gate, "attempt": len(submissions) + 1}  # fmt: skip
            submissions.append(rec)
            if gate["passed"]:
                self.install(code, args.get("name") or "strategy")
                return {"passed": True, "holdout": gate["holdout"], "live_from_next_epoch": True}
            if len(submissions) < 2:
                raise ValueError(f"OOS gate FAILED: {gate['reason']}. Holdout stats: "
                                 f"{json.dumps(gate['holdout'])}. You have one more attempt.")  # fmt: skip
            return {"passed": False, "reason": gate["reason"], "kept_previous": self.name}

        handlers = {
            "get_overview": lambda a: self._overview(arena.metrics_log),
            "analyze": lambda a: self._analyze(a["code"]),
            "backtest": lambda a: self._backtest(a["code"], max(1, n - H - 4000), n - H),
            "submit_strategy": submit,
        }
        tr = await run_tools(
            self.model, system, user, TOOLS, handlers, "submit_strategy", max_turns=16,
            reasoning_effort=self.reasoning_effort,
        )  # fmt: skip
        if tr.final and tr.final.get("notes_to_self"):
            self.notes = tr.final["notes_to_self"]
        base = {
            "epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": "taker", "model": self.model,
            "tools": [c["name"] for t in tr.turns for c in t["calls"]], "turns": tr.turns,
            "tokens": {"in": tr.input_tokens, "out": tr.output_tokens, "reasoning": tr.reasoning_tokens},
            "cost": tr.cost, "seconds": tr.seconds, "error": tr.error, "live_strategy": self.name,
        }  # fmt: skip
        if not submissions:
            arena.log_decision({**base, "name": None, "hypothesis": None, "code": None, "gate": None})
        for i, s in enumerate(submissions):
            gate = s["gate"]
            arena.log_decision({
                **base, **({} if i == len(submissions) - 1 else {"cost": 0.0}),
                "name": s["name"], "hypothesis": s["hypothesis"], "code": s["code"],
                "notes": s["notes"], "attempt": s["attempt"], "live": gate["passed"],
                "gate": {k: gate[k] for k in ("passed", "reason", "insample", "holdout")},
                "similar_to": gate["similar_to"],
            })  # fmt: skip


def _venue_note(cfg) -> str:
    """Several exchanges list the same stock: say which books are the same stock, and the fees."""
    if not cfg.listings:
        return ""
    r = cfg.rules
    lines = [f"- {', '.join([s, *xs])} are the SAME stock on {len(xs) + 1} competing exchanges (same fair "
             "value, separate order books)" for s, xs in cfg.listings.items()]  # fmt: skip
    fees = ", ".join(f"{v} {r.venue_fees.get(v, (r.maker_fee_bps, r.taker_fee_bps))[1]} bps"
                     for s, xs in cfg.listings.items() for v in [s, *xs])  # fmt: skip
    return ("Competing exchanges:\n" + "\n".join(lines) + f"\nTaker fees per venue: {fees}. "
            "obs.meta['listings'] maps each stock to its listings. A long on one listing and a short "
            "on another listing of the same stock is a hedged position.\n")


def _derivatives_note(cfg) -> str:
    """Futures, perps and bonds: what each book is, so a quant can trade the basis or the curve."""
    d = cfg.derivatives
    if not d:
        return ""
    lines = []
    if d.futures:
        f = d.futures
        lines.append(f"- {f.name} is a future on {f.underlying}: fair value = {f.underlying} x exp((policy rate - "
                     f"{f.dividend_yield}%) x time to expiry); it expires and cash-settles at {f.underlying}'s value "
                     f"every {f.expiry_every} steps, when a new contract starts")  # fmt: skip
    for p in d.perps:
        lines.append(f"- {p.name} is a perpetual future on {p.underlying}: no expiry; every {p.funding_every} steps "
                     f"longs pay shorts its premium over {p.underlying} (capped at {p.cap_bps} bps)")  # fmt: skip
    for b in d.bonds:
        lines.append(f"- {b.name} is a {b.years:g}-year zero-coupon government bond paying 10000 cents; its yield "
                     "moves with the central bank's policy rate")  # fmt: skip
    return "Derivatives and bonds:\n" + "\n".join(lines) + "\n"


def _ac(x: np.ndarray, lag: int) -> float:
    x = x[np.isfinite(x)]
    return float(np.corrcoef(x[:-lag], x[lag:])[0, 1]) if len(x) > lag + 2 else 0.0


def _r(x, n=3):
    return None if x is None or not np.isfinite(x) else round(float(x), n)

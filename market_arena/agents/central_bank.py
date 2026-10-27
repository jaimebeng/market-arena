"""An AI central banker: sets the policy rate each quarter (epoch) from macro data and markets."""

from __future__ import annotations

import json

import numpy as np

from ..llm.client import run_tools

SYSTEM = """You are {id}, the monetary policy committee of a central bank, an AI. Each quarter you \
set the policy interest rate.

Mandate: inflation at {target}% over the medium term and, consistent with that, output close to \
potential (an output gap of 0). Financial stability is not your target, but a disorderly market \
can damage the economy: a fall in stock prices lowers output through a wealth effect.

How the economy works here (a small textbook model, one step = one quarter): higher real rates \
(policy rate minus inflation, compared with a neutral real rate of {r_star}%) lower the output gap \
next quarter; a positive output gap raises inflation. Stock prices react to your decision at once \
(about -{duration:.0f} bps of value per +1 percentage point). Rates move in steps of 0.25 and \
cannot go below 0.

Each review: look at the data with the tools, then call set_rate exactly once with a short public \
statement (it is published as a headline) and your rationale (shown on a dashboard)."""

TOOLS = [
    {"type": "function", "function": {
        "name": "get_macro",
        "description": "Every quarter so far: inflation, output gap, the policy rate, your decision, "
                       "and what a standard Taylor rule would have set.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_markets",
        "description": "Per quarter: stock index return, largest drawdown, volatility, trading halts "
                       "and margin calls on leveraged investors.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "set_rate",
        "description": "Set the policy rate for the next quarter. Ends the review.",
        "parameters": {"type": "object", "properties": {
            "rate": {"type": "number", "description": "% per year, multiple of 0.25, >= 0"},
            "statement": {"type": "string", "description": "public statement, 1-2 sentences"},
            "rationale": {"type": "string"},
            "notes_to_self": {"type": "string"}},
            "required": ["rate", "statement", "rationale"]}}},
]


class LLMCentralBank:
    role = "central_bank"

    def __init__(self, agent_id: str, assets: list[str], model: str, params: dict | None = None):
        self.id, self.assets, self.model = agent_id, assets, model
        self.reasoning_effort = (params or {}).get("reasoning_effort")
        self.notes = ""

    @property
    def policies(self):
        return {}

    def on_step(self, ex) -> None:  # sets rates, never trades
        pass

    def _markets(self, arena) -> list[dict]:
        rows = []
        for m in arena.metrics_log:
            mids = [arena.hist.get(a, "mid", m["t0"], m["t1"]) for a in arena.market.fund.names]
            ret = float(np.mean([(x[-1] / x[0] - 1) * 1e4 for x in mids if len(x) > 1]))
            ev = m.get("events", {})
            rows.append({
                "quarter": m["epoch"], "stock_return_bps": round(ret, 1),
                "max_drawdown_pct": max((d["max_drawdown_pct"] for d in ev.get("drawdown", {}).values()), default=None),
                "vol_100_bps": ev.get("vol_100_bps"), "halts": ev.get("halts"),
                "margin_calls": len(ev.get("margin_calls", [])),
            })  # fmt: skip
        return rows

    def _set_rate(self, args: dict) -> dict:
        r = float(args["rate"])
        if not 0 <= r <= 15:
            raise ValueError("rate must be between 0 and 15")
        self._pending = r
        return {"ok": True, "rate": round(r * 4) / 4}

    async def review(self, arena, epoch: int, m: dict) -> None:
        econ = arena.market.economy
        p = econ.p
        system = SYSTEM.format(id=self.id, target=p.pi_target, r_star=p.r_star, duration=p.duration_bps)
        last = econ.history[-1]
        user = (f"Quarter {epoch} just ended ({epoch + 1} of {arena.cfg.n_epochs}). Latest data: "
                f"{json.dumps(last)}. Current rate: {econ.i}%.\nYour notes from last meeting: "
                f"{self.notes or '(none)'}\nInvestigate, then call set_rate.")  # fmt: skip
        self._pending = None
        handlers = {"get_macro": lambda a: econ.history, "get_markets": lambda a: self._markets(arena),
                    "set_rate": self._set_rate}  # fmt: skip
        tr = await run_tools(self.model, system, user, TOOLS, handlers, "set_rate",
                             reasoning_effort=self.reasoning_effort)  # fmt: skip
        final = tr.final or {}
        self.notes = final.get("notes_to_self") or self.notes
        if self._pending is not None:
            econ.pending_rate = self._pending
            econ.statement = (final.get("statement") or "").strip() or None
        arena.log_decision({
            "epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": self.role, "model": self.model,
            "rate": econ.pending_rate if self._pending is not None else None, "previous_rate": econ.i,
            "taylor_rule": econ.taylor(), "macro": last, "statement": final.get("statement"),
            "rationale": final.get("rationale"), "notes": final.get("notes_to_self"),
            "tools": [c["name"] for t in tr.turns for c in t["calls"]], "turns": tr.turns, "error": tr.error,
            "tokens": {"in": tr.input_tokens, "out": tr.output_tokens, "reasoning": tr.reasoning_tokens},
            "cost": tr.cost, "seconds": tr.seconds,
        })  # fmt: skip

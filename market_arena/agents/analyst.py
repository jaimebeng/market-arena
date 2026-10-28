"""Ask the market: an AI analyst that answers questions about a Grand Arena run from its record.

It investigates with tools over the run's live stream (prices, news, decisions, notices, the
reporter's items, quarterly data) and answers with the moments it relied on, so the dashboard can
jump the replay there. It sees only what has happened up to the viewer's playhead: no spoilers.
"""

from __future__ import annotations

import json

import numpy as np

from ..llm.client import run_tools, short_name

SYSTEM = """You are a markets analyst answering a viewer's question about one simulated market \
run (the Grand Arena). Two exchanges: Aurora Systems (A), Bolt Logistics (B), Cobalt Energy (C) \
and the index fund IDX trade on the home exchange; A.X, B.X and C.X are the same stocks on an \
entrant exchange. Some runs add index futures (IDX.F), government bonds (BOND2Y, BOND10Y), \
crypto (COIN, its perpetual future COIN.P, the MEME memecoin) and prediction markets on next \
quarter's events. Prices are in cents. One quarter (epoch) is {spe} steps; one step is about one \
second. Participants are AI agents (market makers, quants writing strategy code, investors, a \
finfluencer, a red team, an AI regulator, an AI central bank), the GLFT formula market maker, and \
a scripted crowd.

Investigate with the tools before answering; check numbers rather than guessing. You can only see \
the run up to step {upto} (the viewer's playhead), so never speculate about what happens later. \
Answer in plain English in at most 120 words, with concrete numbers, then call answer with up to \
4 moments (a step t and a short label) the viewer should jump to. If the data cannot answer the \
question, say so."""

TOOLS = [
    {"type": "function", "function": {
        "name": "overview", "description": "The run so far: participants (role, model), quarters, "
        "assets, the current step, the latest prices and the storyline shocks that have happened.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "price_history", "description": "Mid price and fair value of one asset between two "
        "steps (about 40 evenly spaced points), with the low and the high and when they happened.",
        "parameters": {"type": "object", "properties": {
            "asset": {"type": "string"}, "from_t": {"type": "integer"}, "to_t": {"type": "integer"}},
            "required": ["asset"]}}},
    {"type": "function", "function": {
        "name": "events", "description": "News headlines, the AI reporter's items, regulator notices, "
        "maker chat and forum posts, in time order, optionally filtered.",
        "parameters": {"type": "object", "properties": {
            "kinds": {"type": "array", "items": {"type": "string",
                      "enum": ["news", "commentary", "notice", "chat", "forum"]}},
            "from_t": {"type": "integer"}, "to_t": {"type": "integer"},
            "contains": {"type": "string", "description": "case-insensitive text filter"}}}}},
    {"type": "function", "function": {
        "name": "decisions", "description": "AI agents' decisions at the quarterly reviews: quant "
        "strategies (and whether they passed the out-of-sample gate), investors' targets and posts, "
        "makers' quotes and chat, regulator findings, central bank rates.",
        "parameters": {"type": "object", "properties": {
            "agent": {"type": "string"}, "role": {"type": "string"},
            "epoch": {"type": "integer", "description": "0-based quarter"}}}}},
    {"type": "function", "function": {
        "name": "leaderboard", "description": "Every participant's equity (cents) at a step "
        "(default: now), ranked.",
        "parameters": {"type": "object", "properties": {"t": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "quarter_data", "description": "End-of-quarter data: inflation, output gap, "
        "liquidations, margin calls, halts, drawdowns, the makers' collusion index, exchange shares.",
        "parameters": {"type": "object", "properties": {"epoch": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "predictions", "description": "The prediction-market contracts so far: question, "
        "the model's opening probability, the price after the AI investors' bets, the latest price, "
        "the outcome if decided, and the AI investors' bets (stated probability, side, stake).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "answer", "description": "Give the answer. Ends the investigation.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "moments": {"type": "array", "items": {"type": "object", "properties": {
                "t": {"type": "integer"}, "label": {"type": "string"}}, "required": ["t", "label"]}}},
            "required": ["text"]}}},
]  # fmt: skip

DROP = ("turns", "hash", "prev_hash", "tools", "tokens", "code", "cost", "seconds", "notes")


class RunView:
    """The tools' view of a run's stream, cut at the playhead."""

    def __init__(self, lines: list[dict], upto: int | None = None) -> None:
        start = next(x for x in lines if x["k"] == "start")
        self.start = start
        self.upto = upto if upto is not None else max((x.get("t", 0) for x in lines), default=0)
        self.lines = [x for x in lines if x["k"] == "start" or x.get("t", 0) <= self.upto]
        if not any(x["k"] == "end" and x["t"] <= self.upto for x in lines):
            self.lines = [x for x in self.lines if x["k"] != "end"]
        self.frames = [x for x in self.lines if x["k"] == "f"]
        self.dec = [x for x in self.lines if x["k"] == "decision"]
        self.roles = {a["id"]: a["role"] for a in start["agents"]}
        self.roles |= {d["agent"]: ("finfluencer" if d.get("persona") == "finfluencer" else d["role"]) for d in self.dec}
        self.models = {a["id"]: short_name(a["model"]) if a.get("model") and ":" in a["model"] else (a.get("model") or "scripted")
                       for a in start["agents"]}  # fmt: skip

    def overview(self, _=None) -> dict:
        last = self.frames[-1] if self.frames else {}
        spe = self.start["steps_per_epoch"]
        return {"step_now": self.upto, "quarter_now": self.upto // spe + 1, "quarters": self.start["epochs"],
                "steps_per_quarter": spe, "assets": self.start["assets"], "listings": self.start.get("listings"),
                "participants": {i: f"{r} ({self.models.get(i, '?')})" for i, r in self.roles.items()},
                "prices_now": last.get("mid"), "fair_values_now": last.get("v"),
                "shocks_so_far": [{"t": x["t"], "headline": x["headline"]} for x in self.lines
                                  if x["k"] == "news" and x.get("kind") == "shock"]}  # fmt: skip

    def price_history(self, a: dict) -> dict:
        asset = a["asset"]
        fr = [f for f in self.frames if a.get("from_t", 0) <= f["t"] <= a.get("to_t", self.upto)]
        if not fr or asset not in fr[0]["mid"]:
            raise ValueError(f"no prices for {asset} in that window; assets: {self.start['assets']}")
        mids = [(f["t"], f["mid"][asset]) for f in fr if f["mid"].get(asset) is not None]
        stock = asset.split(".")[0]
        idx = np.linspace(0, len(fr) - 1, min(40, len(fr))).astype(int)
        lo = min(mids, key=lambda x: x[1])
        hi = max(mids, key=lambda x: x[1])
        return {"points": [{"t": fr[i]["t"], "mid": fr[i]["mid"].get(asset), "fair_value": fr[i]["v"].get(stock)} for i in idx],
                "low": {"t": lo[0], "mid": lo[1]}, "high": {"t": hi[0], "mid": hi[1]},
                "change_pct": round((mids[-1][1] / mids[0][1] - 1) * 100, 2)}  # fmt: skip

    def events(self, a: dict) -> list[dict]:
        kinds = set(a.get("kinds") or ["news", "commentary", "notice", "chat", "forum"])
        text = (a.get("contains") or "").lower()
        out = []
        for x in self.lines:
            k = "notice" if x["k"] == "chat" and x.get("kind") == "notice" else x["k"]
            if k not in kinds or not (a.get("from_t", 0) <= x.get("t", 0) <= a.get("to_t", self.upto)):
                continue
            body = x.get("headline") or x.get("text") or ""
            if x["k"] == "commentary":
                body = f"{x['headline']}: {x.get('body', '')}"
            if text and text not in body.lower():
                continue
            out.append({"t": x["t"], "kind": k, "who": x.get("agent"), "asset": x.get("asset"), "text": body[:300]})
        return out[-40:] or [{"note": "no matching events"}]

    def decisions(self, a: dict) -> list[dict]:
        out = []
        for d in self.dec:
            if a.get("agent") and d["agent"] != a["agent"]:
                continue
            if a.get("role") and self.roles.get(d["agent"]) != a["role"] and d.get("role") != a["role"]:
                continue
            if a.get("epoch") is not None and d.get("epoch") != a["epoch"]:
                continue
            out.append({k: (v[:300] if isinstance(v, str) else v) for k, v in d.items() if k not in DROP and v not in (None, [], {})})
        return out[-30:] or [{"note": "no matching decisions"}]

    def leaderboard(self, a: dict) -> list[dict]:
        t = a.get("t", self.upto)
        f = min(self.frames, key=lambda f: abs(f["t"] - t)) if self.frames else None
        if not f:
            return []
        rows = sorted(f["eq"].items(), key=lambda x: -(x[1] or 0))
        return [{"agent": i, "role": self.roles.get(i), "model": self.models.get(i), "equity": e} for i, e in rows
                if self.roles.get(i) not in ("regulator", "central_bank")]  # fmt: skip

    def predictions(self, _=None) -> dict:
        cards: dict[str, dict] = {}
        for x in self.lines:
            if x["k"] in ("pm_open", "pm_resolve"):
                cards[x["id"]] = {**cards.get(x["id"], {}), **{k: v for k, v in x.items() if k != "k"}}
        last = self.frames[-1].get("pm", {}) if self.frames else {}
        for cid, p in last.items():
            if cid in cards:
                cards[cid]["p_now"] = p
        bets = [b | {"t": x["t"]} for x in self.lines if x["k"] == "pm_bets" for b in x["bets"]]
        return {"contracts": list(cards.values()) or "no prediction markets in this run", "ai_bets": bets[-40:]}

    def quarter_data(self, a: dict) -> list[dict]:
        eps = [x for x in self.lines if x["k"] == "epoch"]
        if a.get("epoch") is not None:
            eps = [x for x in eps if x["epoch"] == a["epoch"]]
        return [{k: v for k, v in x.items() if k != "k"} for x in eps] or [{"note": "no quarter has ended yet"}]


async def ask(lines: list[dict], question: str, model: str, upto: int | None = None) -> dict:
    view = RunView(lines, upto)
    handlers = {"overview": view.overview, "price_history": view.price_history, "events": view.events,
                "decisions": view.decisions, "leaderboard": view.leaderboard,
                "quarter_data": view.quarter_data, "predictions": view.predictions,
                "answer": lambda a: {"ok": True}}  # fmt: skip
    system = SYSTEM.format(spe=view.start["steps_per_epoch"], upto=view.upto)
    tr = await run_tools(model, system, f"Question: {question}", TOOLS, handlers, "answer", max_turns=8)
    final = tr.final or {}
    moments = [m for m in final.get("moments") or [] if isinstance(m.get("t"), int) and 0 <= m["t"] <= view.upto]
    return {"answer": final.get("text") or "I could not find an answer in this run's record.",
            "moments": moments[:4], "upto": view.upto, "model": model,
            "tools": [c["name"] for t in tr.turns for c in t["calls"]],
            "seconds": tr.seconds, "cost": round(tr.cost, 5), "error": tr.error}  # fmt: skip


if __name__ == "__main__":  # python -m market_arena.agents.analyst web/public/grand/<id>.json "question" [upto]
    import asyncio
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    data = json.loads(open(sys.argv[1]).read())
    up = int(sys.argv[3]) if len(sys.argv) > 3 else None
    print(json.dumps(asyncio.run(ask(data["lines"], sys.argv[2], "meta:muse-spark-1.3-contributor", up)), indent=1))

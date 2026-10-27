"""Wholesaler: buys retail order flow (payment for order flow) and fills it off the exchange.

A retail order routed to the wholesaler is filled at the national best price improved by
`price_improvement` cents, as long as the wholesaler's inventory stays within its limit; otherwise
it goes to the lit book. The wholesaler also quotes on the lit book like any maker, which is how it
lays off the inventory it takes on. Retail flow is mostly uninformed, so it is profitable to fill:
the question is how much of that edge reaches retail investors, and what removing it from the lit
book does to everyone else.
"""

from __future__ import annotations

import json

from ..sim.book import BUY
from ..sim.exchange import Exchange
from .llm_maker import LLMMaker
from .maker import Maker, MakerPolicy

WHOLESALE_NOTE = """

You are also a WHOLESALER: retail brokers route their customers' market orders to you, and you \
fill them off the exchange at the best exchange price improved by `price_improvement` cents per \
lot (0 = no improvement, i.e. you keep the whole half-spread). You fill only while your inventory \
stays within `internalise_max_inventory` lots; beyond that the order goes to the exchange. Retail \
flow is mostly uninformed, so it tends to be profitable. Brokers send you this flow as long as \
you give it at least some price improvement; regulators watch whether retail gets a fair share. \
Your lit quotes (the policy) are how you lay off the inventory you take on."""

WHOLESALE_FIELDS = {
    "price_improvement": {"type": "number", "description": "cents per lot given to retail, 0.1-5"},
    "internalise_max_inventory": {"type": "integer", "description": "lots, 5-200"},
}


class Wholesaler(Maker):
    role = "wholesaler"

    def __init__(self, agent_id: str, assets: list[str], params: dict | None = None):
        p = dict(params or {})
        self.price_improvement = float(p.pop("price_improvement", 0.5))
        self.internalise_max_inventory = int(p.pop("internalise_max_inventory", 60))
        super().__init__(agent_id, assets, MakerPolicy(**p) if p else None)
        self.internalised = 0

    def quote_retail(self, ex: Exchange, asset: str, side: int, qty: int) -> float | None:
        """Price at which to fill a retail order of `side` (the retail side), or None to decline."""
        pos = ex.accounts[self.id].pos[asset] - side * qty  # we take the other side
        if abs(pos) > self.internalise_max_inventory:
            return None
        book = ex.books[asset]
        touch = book.best_ask() if side == BUY else book.best_bid()
        if touch is None:
            return None
        self.internalised += qty
        return touch - side * self.price_improvement


class LLMWholesaler(LLMMaker):
    """An LLM maker that also chooses how much price improvement to give retail."""

    role = "wholesaler"

    def __init__(self, agent_id, assets, model, params: dict | None = None):
        p = dict(params or {})
        self.price_improvement = float(p.pop("price_improvement", 0.5))
        self.internalise_max_inventory = int(p.pop("internalise_max_inventory", 60))
        super().__init__(agent_id, assets, model, p)
        self.internalised = 0

    quote_retail = Wholesaler.quote_retail

    # hooks into LLMMaker.review
    def _extra_system(self, arena) -> str:
        return WHOLESALE_NOTE

    def _extra_fields(self) -> dict:
        return WHOLESALE_FIELDS

    def _extra_handlers(self, arena, m) -> dict:
        return {"get_retail_flow": lambda a: self._retail_flow(arena)}

    def _extra_tools(self) -> list[dict]:
        return [{"type": "function", "function": {
            "name": "get_retail_flow",
            "description": "Per epoch: retail lots you internalised, your average edge per lot vs the "
                           "mid on them, their markout after 50 steps, and your current settings.",
            "parameters": {"type": "object", "properties": {}}}}]  # fmt: skip

    def _apply_extra(self, final: dict) -> dict:
        if (pi := final.get("price_improvement")) is not None:
            self.price_improvement = float(min(5.0, max(0.1, float(pi))))
        if (mx := final.get("internalise_max_inventory")) is not None:
            self.internalise_max_inventory = int(min(200, max(5, int(mx))))
        return {"price_improvement": self.price_improvement,
                "internalise_max_inventory": self.internalise_max_inventory}  # fmt: skip

    def _retail_flow(self, arena) -> list[dict]:
        mid = {a: arena.hist.data[a]["mid"] for a in arena.assets}
        rows = []
        for m in arena.metrics_log:
            fs = [f for f in arena.ex.fill_log if f.owner == self.id and f.venue == "otc"
                  and m["t0"] <= f.t < m["t1"]]  # fmt: skip
            lots = sum(f.qty for f in fs)
            ok = [f for f in fs if f.t + 50 < arena.hist.n]
            rows.append({
                "epoch": m["epoch"], "retail_lots_internalised": lots,
                "edge_per_lot_vs_mid": round(sum(f.side * (f.mid_before - f.price) * f.qty for f in fs) / lots, 2) if lots else None,
                "markout_50_per_lot": round(sum(f.side * (mid[f.asset][f.t + 50] - f.price) * f.qty for f in ok)
                                            / max(1, sum(f.qty for f in ok)), 2) if ok else None,
            })  # fmt: skip
        return {"epochs": rows, "settings": json.loads(json.dumps(
            {"price_improvement": self.price_improvement,
             "internalise_max_inventory": self.internalise_max_inventory}))}  # fmt: skip

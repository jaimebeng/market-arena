"""Scripted spoofer: the planted wrongdoer that market surveillance is scored against.

Each cycle it rests a large order one tick behind the touch on one side (fake pressure that
order-book-imbalance traders read as demand), rests a small genuine order at the opposite touch
(the bait those traders hit), and cancels the large order a few steps later, before it can trade.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..sim.book import BUY, SELL
from ..sim.exchange import Exchange


class SpoofParams(BaseModel):
    spoof_size: int = 25  # lots in the fake order
    bait_size: int = 2  # lots in the genuine order
    cycle: int = 30  # steps between spoofs
    hold: int = 4  # steps the fake order rests before it is cancelled
    max_position: int = 10  # lots; beyond this it unwinds with market orders


class Spoofer:
    role = "taker"

    def __init__(self, agent_id: str, assets: list[str], seed: int, params: dict | None = None):
        self.id = agent_id
        self.assets = assets
        self.p = SpoofParams(**(params or {}))
        self.rng = np.random.default_rng(seed)
        self.offset = {a: int(self.rng.integers(self.p.cycle)) for a in assets}
        self.live: dict[str, list[int]] = {a: [] for a in assets}  # fake orders to cancel
        self.bait: dict[str, list[int]] = {a: [] for a in assets}
        self.model = "scripted: spoofer"
        self.name = "spoofing"

    @property
    def policies(self):
        return {}

    def on_step(self, ex: Exchange) -> None:
        tick = ex.rules.tick
        for a in self.assets:
            pos = ex.accounts[self.id].pos[a]
            if abs(pos) > self.p.max_position:
                ex.market(self.id, a, SELL if pos > 0 else BUY, 1)
            phase = (ex.t + self.offset[a]) % self.p.cycle
            if phase == self.p.hold:
                self.live[a] = [oid for oid in self.live[a] if not ex.cancel(a, oid)]
            if phase != 0:
                continue
            for oid in self.bait[a]:  # unfilled genuine orders from the last cycle
                ex.cancel(a, oid)
            self.bait[a] = []
            book = ex.books[a]
            bb, ba = book.best_bid(), book.best_ask()
            if bb is None or ba is None:
                continue
            # fake pressure that helps unwind inventory (long -> fake bids, sell the bounce)
            push = BUY if pos > 2 else SELL if pos < -2 else int(self.rng.choice((BUY, SELL)))
            if push == BUY:  # fake bids, genuine offer at the ask
                spoof = ex.limit(self.id, a, BUY, bb - tick, self.p.spoof_size, post_only=True)
                bait = ex.limit(self.id, a, SELL, ba, self.p.bait_size, post_only=True)
            else:  # fake offers, genuine bid at the bid
                spoof = ex.limit(self.id, a, SELL, ba + tick, self.p.spoof_size, post_only=True)
                bait = ex.limit(self.id, a, BUY, bb, self.p.bait_size, post_only=True)
            self.live[a] += [spoof] if spoof is not None else []
            self.bait[a] += [bait] if bait is not None else []

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
    spoof_size: int = 25  # lots in the fake order (0: no fake order, only the genuine one)
    bait_size: int = 2  # lots in the genuine order
    cycle: int = 30  # steps between spoofs
    hold: int = 4  # steps the fake order rests before it is cancelled
    max_position: int = 10  # lots; beyond this it unwinds with market orders
    layers: int = 1  # fake size split over this many price levels behind the touch
    bait_ttl: int | None = None  # steps the genuine order rests; None: until the next cycle


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
        self.fake_lots = 0  # lots of fake (non-bona-fide) orders placed, all assets
        self.model = "scripted: spoofer"
        self.name = "spoofing"

    @property
    def policies(self):
        return {}

    def _cancel_bait(self, ex: Exchange, a: str) -> None:
        for oid in self.bait[a]:  # unfilled genuine orders
            ex.cancel(a, oid)
        self.bait[a] = []

    def on_step(self, ex: Exchange) -> None:
        p, tick = self.p, ex.rules.tick
        for a in self.assets:
            pos = ex.accounts[self.id].pos[a]
            if abs(pos) > p.max_position:
                ex.market(self.id, a, SELL if pos > 0 else BUY, 1)
            phase = (ex.t + self.offset[a]) % p.cycle
            if phase == p.hold:
                self.live[a] = [oid for oid in self.live[a] if not ex.cancel(a, oid)]
            if p.bait_ttl is not None and phase == p.bait_ttl:
                self._cancel_bait(ex, a)
            if phase != 0:
                continue
            self._cancel_bait(ex, a)
            book = ex.books[a]
            bb, ba = book.best_bid(), book.best_ask()
            if bb is None or ba is None:
                continue
            # fake pressure that helps unwind inventory (long -> fake bids, sell the bounce)
            push = BUY if pos > 2 else SELL if pos < -2 else int(self.rng.choice((BUY, SELL)))
            layers = max(1, p.layers)
            size = max(1, p.spoof_size // layers) if p.spoof_size > 0 else 0
            for k in range(1, layers + 1) if size else ():
                px = bb - k * tick if push == BUY else ba + k * tick
                oid = ex.limit(self.id, a, push, px, size, post_only=True)
                if oid is not None:
                    self.live[a].append(oid)
                    self.fake_lots += size
            # genuine order at the opposite touch: fake bids -> offer at the ask, and vice versa
            bait = (ex.limit(self.id, a, SELL, ba, p.bait_size, post_only=True) if push == BUY
                    else ex.limit(self.id, a, BUY, bb, p.bait_size, post_only=True))  # fmt: skip
            self.bait[a] += [bait] if bait is not None else []

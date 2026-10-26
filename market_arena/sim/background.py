"""Scripted background order flow.

- ZeroIntelligenceFlow: random limit orders around the mid with finite lifetimes plus random
  market orders. Gives the book depth and gives makers uninformed flow to earn on.
- InformedTrader: sees the hidden fair value and trades when the price is wrong. Creates
  adverse selection for makers and makes order flow predictive of future returns.
- IndexFlow: occasional one-sided bursts in the index only, opening index-vs-basket gaps.
"""

from __future__ import annotations

import heapq

import numpy as np
from pydantic import BaseModel

from .book import BUY, SELL
from .exchange import Exchange


class ZIParams(BaseModel):
    limit_rate: float = 1.2  # limit orders per step
    market_rate: float = 0.35  # market orders per step
    offset_min: int = 3  # price units (cents) from the reference; rounded to the tick
    offset_max: int = 25
    lifetime_mean: float = 60.0  # steps
    size_mean: float = 3.0  # lots (geometric)
    # information diffusion: new limit orders centre on mid + kappa * (lagged value - mid)
    anchor_kappa: float = 0.3
    anchor_lag: int = 150  # steps; the crowd learns the fair value with this delay


class InformedParams(BaseModel):
    rate: float = 0.03  # chance per step of acting
    threshold_bps: float = 8.0  # mispricing needed to trade
    size: int = 2  # lots per threshold of mispricing
    max_size: int = 12
    noise_bps: float = 1.0  # error in its read of fair value


class IndexFlowParams(BaseModel):
    burst_rate: float = 0.002  # chance per step of starting a burst
    burst_len: int = 40
    size: int = 3


class ZeroIntelligenceFlow:
    owner = "noise"

    def __init__(self, ex: Exchange, asset: str, p: ZIParams, rng: np.random.Generator):
        self.ex, self.asset, self.p, self.rng = ex, asset, p, rng
        self._expiry: list[tuple[int, int]] = []  # (expiry step, order id)

    def _size(self) -> int:
        return int(self.rng.geometric(1 / self.p.size_mean))

    def seed(self, price: float, levels: int = 15) -> None:
        tick = self.ex.rules.tick
        for k in range(1, levels + 1):
            for side in (BUY, SELL):
                self._place(side, price - side * k * tick)

    def _place(self, side: int, px: float) -> None:
        oid = self.ex.limit(self.owner, self.asset, side, px, self._size(), post_only=True)
        if oid is not None:
            life = int(self.rng.exponential(self.p.lifetime_mean)) + 1
            heapq.heappush(self._expiry, (self.ex.t + life, oid))

    def step(self, lagged_value: float | None = None) -> None:
        ex, p, rng = self.ex, self.p, self.rng
        while self._expiry and self._expiry[0][0] <= ex.t:
            _, oid = heapq.heappop(self._expiry)
            if not ex.cancel(self.asset, oid):  # too young under a speed bump: retry later
                o = ex.books[self.asset].orders[oid]
                heapq.heappush(self._expiry, (o.t + ex.rules.min_resting_steps, oid))
        mid = ex.mid(self.asset)
        if lagged_value is not None:
            mid += p.anchor_kappa * (lagged_value - mid)
        for _ in range(rng.poisson(p.limit_rate)):
            side = BUY if rng.random() < 0.5 else SELL
            off = rng.integers(p.offset_min, p.offset_max + 1)
            self._place(side, mid - side * off)
        for _ in range(rng.poisson(p.market_rate)):
            side = BUY if rng.random() < 0.5 else SELL
            ex.market(self.owner, self.asset, side, self._size())


class InformedTrader:
    owner = "informed"

    def __init__(self, ex: Exchange, p: InformedParams, rng: np.random.Generator):
        self.ex, self.p, self.rng = ex, p, rng

    def step(self, values: dict[str, float]) -> None:
        for asset in self.ex.assets:
            if self.rng.random() >= self.p.rate:
                continue
            mid = self.ex.mid(asset)
            if mid <= 0:
                continue
            seen = values[asset] * (1 + self.rng.normal() * self.p.noise_bps * 1e-4)
            gap_bps = (seen / mid - 1) * 1e4
            if abs(gap_bps) > self.p.threshold_bps:
                size = min(self.p.max_size, int(self.p.size * abs(gap_bps) / self.p.threshold_bps))
                self.ex.market(self.owner, asset, BUY if gap_bps > 0 else SELL, size)


class IndexFlow:
    owner = "index_flow"

    def __init__(self, ex: Exchange, asset: str, p: IndexFlowParams, rng: np.random.Generator):
        self.ex, self.asset, self.p, self.rng = ex, asset, p, rng
        self.left, self.side = 0, BUY

    def step(self) -> None:
        if self.left == 0 and self.rng.random() < self.p.burst_rate:
            self.left = self.p.burst_len
            self.side = BUY if self.rng.random() < 0.5 else SELL
        if self.left > 0:
            self.left -= 1
            if self.rng.random() < 0.5:
                self.ex.market(self.owner, self.asset, self.side, self.p.size)

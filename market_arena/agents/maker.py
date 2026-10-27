"""Market maker: the fast path that turns a quoting policy into resting orders."""

from __future__ import annotations

import math
from collections import deque

from pydantic import BaseModel, Field

from ..sim.book import BUY, SELL
from ..sim.exchange import Exchange


class MakerPolicy(BaseModel):
    """Affine quoting policy, the same shape as the GLFT and Nash/Pareto benchmarks.

    reservation r = mid - skew * q;   bid = r - half_spread;   ask = r + half_spread
    Units: price units (cents) and lots. Positive skew leans quotes against inventory.
    """

    half_spread: float = Field(5.0, ge=0.5, le=100)
    skew: float = Field(0.0, ge=-5, le=20)
    size: int = Field(2, ge=1, le=20)
    max_inventory: int = Field(20, ge=1, le=200)
    requote_every: int = Field(5, ge=1, le=100)
    # optional crisis rule: if the mid moves this many bps within pull_window steps, cancel
    # quotes and stay out of the market for pull_steps steps (a pre-committed kill switch)
    pull_if_move_bps: float | None = Field(None, ge=1, le=2000)
    pull_window: int | None = Field(None, ge=5, le=2000)  # default 50
    pull_steps: int | None = Field(None, ge=1, le=5000)  # default 100


class Maker:
    role = "maker"

    def __init__(self, agent_id: str, assets: list[str], policy: MakerPolicy | None = None):
        self.id = agent_id
        self.assets = assets
        self.policies: dict[str, MakerPolicy] = {a: policy or MakerPolicy() for a in assets}
        self.model: str | None = None
        self.pulls = 0  # times a crisis rule pulled the quotes
        self._mids: dict[str, deque] = {}
        self._paused: dict[str, int] = {}

    def quotes(self, ex: Exchange, asset: str) -> tuple[int | None, int | None]:
        p = self.policies[asset]
        q = ex.accounts[self.id].pos[asset]
        r = ex.mid(asset) - p.skew * q
        bid = math.floor(r - p.half_spread) if q + p.size <= p.max_inventory else None
        ask = math.ceil(r + p.half_spread) if q - p.size >= -p.max_inventory else None
        return bid, ask

    def _pull(self, ex: Exchange, asset: str, p: MakerPolicy) -> bool:
        """Apply the crisis rule. True while the maker is out of the market for this asset."""
        h = self._mids.get(asset)
        if h is None or h.maxlen != (p.pull_window or 50) + 1:
            h = self._mids[asset] = deque(maxlen=(p.pull_window or 50) + 1)
        h.append(ex.mid(asset))
        if ex.t < self._paused.get(asset, -1):
            return True
        if len(h) > 1 and h[0] > 0 and abs(h[-1] / h[0] - 1) * 1e4 >= p.pull_if_move_bps:
            if ex.cancel_all(self.id, asset):
                self._paused[asset] = ex.t + (p.pull_steps or 100)
                self.pulls += 1
                h.clear()
                return True
        return False

    def on_step(self, ex: Exchange) -> None:
        for asset in self.assets:
            p = self.policies[asset]
            if p.pull_if_move_bps and self._pull(ex, asset, p):
                continue
            if ex.t % p.requote_every:
                continue
            if not ex.cancel_all(self.id, asset):
                continue  # speed bump: some quotes are too young to cancel
            bid, ask = self.quotes(ex, asset)
            if bid is not None:
                ex.limit(self.id, asset, BUY, bid, p.size, post_only=True)
            if ask is not None:
                ex.limit(self.id, asset, SELL, ask, p.size, post_only=True)

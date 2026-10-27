"""Newswire: turns fair-value moves into headlines that agents can read.

Every news jump in the fundamentals produces a templated headline whose tone follows the sign and
size of the move, except that a share of headlines is misleading (tone opposite to the move), as
real news often is. Optional scheduled earnings releases (a public calendar) add a surprise to fair
value and an unambiguous headline. Headlines are templated, not written by a model: cheap,
reproducible, and with the true size of each move known for analysis.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from .fundamentals import Fundamentals

COMPANIES = {"A": "Aurora Systems", "B": "Bolt Logistics", "C": "Cobalt Energy"}

GOOD = {
    "small": ["{co} shares edge up as analyst nudges target higher",
              "{co} wins renewal of a mid-sized supply contract",
              "Channel checks point to steady demand at {co}"],
    "large": ["{co} lands its largest-ever contract",
              "{co} raises full-year guidance",
              "Regulator clears {co}'s flagship product ahead of schedule"],
}
BAD = {
    "small": ["{co} flags slightly softer orders in one region",
              "Analyst trims {co} target on margin worries",
              "{co} delays a minor product update"],
    "large": ["{co} cuts full-year guidance",
              "Regulator opens probe into {co}'s accounting",
              "{co} loses its biggest customer"],
}


class NewsParams(BaseModel):
    misleading: float = 0.15  # share of headlines whose tone is opposite to the move
    large_bps: float = 60.0  # moves at least this big get "large" headlines
    earnings_every: int | None = None  # steps between earnings releases per company (staggered)
    earnings_bps: float = 80.0  # std of the earnings surprise in fair value


def company(asset: str) -> str:
    return COMPANIES.get(asset, f"{asset} Corp")


class NewsWire:
    def __init__(self, fund: Fundamentals, p: NewsParams, rng: np.random.Generator) -> None:
        self.fund, self.p, self.rng = fund, p, rng
        self.items: list[dict] = []

    def calendar(self, t0: int, t1: int) -> list[dict]:
        """Scheduled earnings releases in [t0, t1): public in advance."""
        if not self.p.earnings_every:
            return []
        out = []
        for i, a in enumerate(self.fund.names):
            offset = (i + 1) * self.p.earnings_every // (len(self.fund.names) + 1)
            first = offset + max(0, (t0 - offset + self.p.earnings_every - 1) // self.p.earnings_every) * self.p.earnings_every
            out += [{"t": t, "asset": a, "company": company(a)} for t in range(first, t1, self.p.earnings_every)]
        return sorted(out, key=lambda x: x["t"])

    def step(self, t: int) -> None:
        for asset, bps in self.fund.last_jumps:
            self._headline(t, asset, bps)
        for e in self.calendar(t, t + 1):
            bps = float(self.rng.normal() * self.p.earnings_bps)
            self.fund.shock({e["asset"]: bps})
            word = "beats" if bps > 0 else "misses"
            size = "comfortably" if abs(bps) > self.p.earnings_bps else "narrowly"
            self.items.append({"t": t, "asset": e["asset"], "kind": "earnings", "true_bps": round(bps, 1),
                               "headline": f"{company(e['asset'])} {size} {word} earnings estimates"})  # fmt: skip

    def _headline(self, t: int, asset: str, bps: float) -> None:
        tone_up = (bps > 0) != (self.rng.random() < self.p.misleading)
        size = "large" if abs(bps) >= self.p.large_bps else "small"
        pool = (GOOD if tone_up else BAD)[size]
        text = pool[int(self.rng.integers(len(pool)))].format(co=company(asset))
        self.items.append({"t": t, "asset": asset, "kind": "news", "true_bps": round(bps, 1),
                           "misleading": (bps > 0) != tone_up, "headline": text})  # fmt: skip

    def public(self, t0: int, t1: int) -> list[dict]:
        """Headlines in [t0, t1) as agents see them (no true size, no misleading flag)."""
        return [{"t": n["t"], "asset": n["asset"], "kind": n["kind"], "headline": n["headline"]}
                for n in self.items if t0 <= n["t"] < t1]  # fmt: skip


def news_response(items: list[dict], mid: np.ndarray, horizons=(10, 100, 500, 1500), min_bps: float = 20.0,
                  asset_mid: dict | None = None) -> dict:  # fmt: skip
    """How much of each news move the market price had absorbed h steps later, as a share of the
    true move (1 = fully priced in, below 1 = under-reaction, above 1 = over-reaction). Averaged
    over news items with |move| >= min_bps; misleading headlines reported separately."""
    out = {}
    for label, keep in (("all", lambda n: True), ("misleading", lambda n: n.get("misleading"))):
        for h in horizons:
            r = []
            for n in items:
                if abs(n["true_bps"]) < min_bps or not keep(n):
                    continue
                m = (asset_mid or {}).get(n["asset"], mid)
                t = n["t"]
                if t < 1 or t + h >= len(m) or not np.isfinite(m[t - 1]) or not np.isfinite(m[t + h]):
                    continue
                r.append((m[t + h] / m[t - 1] - 1) * 1e4 / n["true_bps"])
            if r:
                out[f"{label}_{h}"] = round(float(np.median(r)), 3)
                out[f"{label}_n"] = len(r)
    return out

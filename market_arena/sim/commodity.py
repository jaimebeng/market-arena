"""Crude oil: a commodity whose price follows its inventories, and futures with a real curve.

Oil (a component of kind "commodity": not in the index, no earnings) trades like any other book,
but its fair value has a structural part on top of the usual random walk. Inventories are kept in
days of normal consumption ("cover"). Each step they change by supply minus demand, so a war that
cuts supply by 15% drains them steadily, and the price rises as cover falls (a scarcity premium,
elasticity `elasticity`). Demand falls a little as the price rises, which slows the drain. A
strategic reserve release adds supply. Oil moves the stocks that depend on it (`stock_betas`:
an energy producer up, a logistics firm down).

Oil futures (OIL.F) price off the theory of storage: fair = spot * exp((r + storage - convenience
yield) * tau), and the convenience yield grows as inventories fall, so a well-supplied market is
in contango and a scarce one in steep backwardation, as oil was in 2022. Each contract expires at
the end of a quarter and is cash-settled at the spot fair value, like the index future.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from .derivatives import STEPS_PER_YEAR


class SupplyEvent(BaseModel):
    at_step: int
    supply_pct: float  # change in supply, % of normal consumption (a war: -15; a reserve release: +5)
    steps: int  # how long it lasts
    headline: str = ""
    reserve: bool = False  # drawn from the strategic reserve (limited by reserve_days)


class OilParams(BaseModel):
    asset: str = "OIL"
    cover_days: float = 60.0  # starting inventories, in days of normal consumption
    days_per_step: float = 0.06  # 1,500 steps = one quarter (90 days)
    elasticity: float = 1.2  # log price per log fall in days of cover
    demand_response: float = 0.08  # consumption falls by this much per +1 in log price
    stock_betas: dict[str, float] = {}  # d log stock per d log oil, e.g. {C: 0.5, B: -0.35}
    events: list[SupplyEvent] = []
    reserve_days: float = 25.0  # the strategic reserve, in days of consumption
    futures: str | None = "OIL.F"
    expiry_every: int = 1500
    storage_pct: float = 4.0  # % a year to store a barrel
    convenience_pct: float = 3.0  # convenience yield at normal inventories, % a year


class OilMarket:
    """Steps oil's inventories and passes oil's moves on to the stocks that depend on it."""

    def __init__(self, fund, p: OilParams, ex=None) -> None:
        self.fund, self.p, self.ex = fund, p, ex
        self.i = fund.names.index(p.asset)
        self.cover = p.cover_days
        self.reserve = p.reserve_days
        self.scarcity = 0.0  # the structural part of log price
        self._last = float(fund.log_v[self.i])
        self.betas = {fund.names.index(a): b for a, b in p.stock_betas.items()}
        self.events = list(p.events)  # scheduled, plus reserve releases decided during the run
        self.releases: list[dict] = []  # releases decided during the run (an AI energy agency)
        self.history: list[dict] = []
        self.settlements: list[dict] = []

    def supply(self, t: int) -> float:
        """Supply this step, as a share of normal consumption."""
        s = 1.0
        for e in self.events:
            if e.at_step <= t < e.at_step + e.steps:
                if e.reserve:
                    draw = e.supply_pct / 100 * self.p.days_per_step
                    if self.reserve < draw:
                        continue
                    self.reserve -= draw
                s += e.supply_pct / 100
        return s

    def step(self, t: int) -> None:
        f, i = self.fund, self.i
        demand = 1.0 - self.p.demand_response * self.scarcity  # demand falls as scarcity raises the price
        self.cover = max(3.0, self.cover + (self.supply(t) - demand) * self.p.days_per_step)
        scarcity = -self.p.elasticity * math.log(self.cover / self.p.cover_days)
        f.log_v[i] += scarcity - self.scarcity
        self.scarcity = scarcity
        move = float(f.log_v[i]) - self._last  # this step's oil move: random walk, news and scarcity
        for j, b in self.betas.items():
            f.log_v[j] += b * move
        self._last = float(f.log_v[i])
        if t % 50 == 0:
            self.history.append({"t": t, "cover_days": round(self.cover, 2), "reserve_days": round(self.reserve, 2),
                                 "price": round(math.exp(self._last), 1)})  # fmt: skip

    def release(self, t: int, days: float, over: int, reason: str = "") -> dict:
        """Release `days` of consumption from the strategic reserve over `over` steps."""
        days = max(0.0, min(days, self.reserve))
        rec = {"at_step": t, "steps": over, "reserve": True,
               "supply_pct": round(days / (over * self.p.days_per_step) * 100, 3),
               "headline": f"Energy agency releases {days:.1f} days of oil from the strategic reserve"
                           + (f": {reason}" if reason else "")}  # fmt: skip
        self.releases.append(rec)
        self.events.append(SupplyEvent(**rec))
        return rec

    def convenience(self) -> float:
        """Convenience yield, % a year: rises steeply as inventories fall."""
        return self.p.convenience_pct * (self.p.cover_days / self.cover) ** 3

    def futures_value(self, spot: float, t: int, rate: float) -> float:
        tau = (self.p.expiry_every - t % self.p.expiry_every) / STEPS_PER_YEAR
        return spot * math.exp((rate + self.p.storage_pct - self.convenience()) / 100 * tau)

    def state(self) -> dict:
        return {"cover_days": round(self.cover, 1), "normal_cover_days": self.p.cover_days,
                "strategic_reserve_days": round(self.reserve, 1),
                "convenience_yield_pct": round(self.convenience(), 2)}  # fmt: skip

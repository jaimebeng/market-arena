"""A stochastic storyline: a run's surprises are drawn from its seed.

Every seed is a different story (which company gets a takeover bid, when tariffs hit, whether a
fund is forced to liquidate), and the same seed is the same story. The drawn events are written
into the run's config, which the run records, so a run still replays exactly.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from .news import company
from .participants import FireSaleParams
from .schedule import Shock

STOCK_UP = ["{co} beats estimates and raises guidance", "Takeover bid for {co} at a large premium",
            "Regulator approves {co}'s flagship product", "{co} announces a large buyback"]  # fmt: skip
STOCK_DOWN = ["{co} cuts guidance; CFO resigns", "Short seller alleges accounting fraud at {co}",
              "{co} recalls its flagship product", "{co} loses its largest customer"]  # fmt: skip
MACRO_UP = ["Trade deal signed; tariffs lifted", "Inflation falls faster than expected",
            "Government announces a large stimulus package"]  # fmt: skip
MACRO_DOWN = ["Breaking: 100% tariffs announced; risk assets sell off",
              "Major bank fails; contagion fears spread", "Oil price spikes on supply shock"]  # fmt: skip


class StorylineParams(BaseModel):
    shocks: tuple[int, int] = (1, 3)  # how many news shocks (min, max)
    shock_bps: float = 180.0  # typical size, in bps of fair value (each is 0.5x to 1.5x this)
    market_wide: float = 0.3  # share of shocks that hit every stock (macro news)
    fire_sale: float = 0.5  # probability that a fund is forced to liquidate one stock
    fire_sale_qty: tuple[int, int] = (800, 2000)  # lots
    window: tuple[float, float] = (0.15, 0.85)  # events fall within this share of the run
    drawn: bool = False  # set once drawn: the run's config then holds the events themselves


def draw_storyline(cfg):
    """Return cfg with the storyline's events added to its shocks (and population fire sale)."""
    s = cfg.storyline
    if s is None or s.drawn:
        return cfg
    rng = np.random.default_rng([cfg.seed, 11])
    total = cfg.steps_per_epoch * cfg.n_epochs
    names = list(cfg.components)

    def when() -> int:
        return int(rng.uniform(*s.window) * total)

    def pick(pool: list[str]) -> str:
        return pool[int(rng.integers(len(pool)))]

    shocks = list(cfg.shocks)
    for _ in range(int(rng.integers(s.shocks[0], s.shocks[1] + 1))):
        at = when()
        bps = float(rng.choice([-1.0, 1.0]) * s.shock_bps * rng.uniform(0.5, 1.5))
        if rng.random() < s.market_wide:
            shocks.append(Shock(at_step=at, asset="*", bps=round(bps, 1),
                                headline=pick(MACRO_UP if bps > 0 else MACRO_DOWN)))  # fmt: skip
        else:
            a = names[int(rng.integers(len(names)))]
            shocks.append(Shock(at_step=at, asset=a, bps=round(bps, 1),
                                headline=pick(STOCK_UP if bps > 0 else STOCK_DOWN).format(co=company(a))))  # fmt: skip
    pop = cfg.population
    if pop is not None and pop.fire_sale is None and rng.random() < s.fire_sale:
        a = names[int(rng.integers(len(names)))]
        fire = FireSaleParams(at_step=when(), asset=a, qty=int(rng.integers(*s.fire_sale_qty)), over=100)
        pop = pop.model_copy(update={"fire_sale": fire})
        shocks.append(Shock(at_step=fire.at_step, asset=a, bps=0.0,
                            headline=f"Reports: a large fund is being forced to liquidate its holdings of {company(a)}"))  # fmt: skip
    shocks.sort(key=lambda x: x.at_step)
    return cfg.model_copy(update={"shocks": shocks, "population": pop,
                                  "storyline": s.model_copy(update={"drawn": True})})  # fmt: skip

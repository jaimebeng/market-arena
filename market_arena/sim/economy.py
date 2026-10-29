"""A stylised macroeconomy around the market: inflation, the output gap and a policy rate.

One epoch is one quarter. A textbook three-equation model:
    output gap   y' = rho_y y - a (i - r* - pi) - wealth * market drawdown + e_y
    inflation    pi' = rho_pi pi + (1 - rho_pi) pi* + b y + c * oil move + e_pi
    policy rate  set by a Taylor rule (default) or by an AI central banker
Links to the market: a rate change reprices stocks at once (duration: `duration_bps` of value per
percentage point), and earnings surprises lean with the output gap. Falling stock prices feed back
into output through a wealth effect. With oil in the market (sim/commodity.py), a quarter's rise in
the oil price passes into inflation and takes some output away: a supply shock, the central bank's
hardest case. Deliberately small: a yardstick for how an AI central bank
reacts to markets, not a forecast.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from .fundamentals import Fundamentals


class EconomyParams(BaseModel):
    r_star: float = 1.0  # neutral real rate, %
    pi_target: float = 2.0  # %
    pi0: float = 3.5  # starting inflation, % (above target: the central bank has work to do)
    y0: float = 0.5  # starting output gap, %
    i0: float = 4.0  # starting policy rate, %
    rho_y: float = 0.75
    rho_pi: float = 0.7
    a: float = 0.35  # output response to the real rate gap
    b: float = 0.25  # Phillips curve slope
    wealth: float = 0.15  # output gap points lost per % fall in stock prices in a quarter
    sd_y: float = 0.35
    sd_pi: float = 0.25
    duration_bps: float = 400.0  # stock value change per 1 pp rate change (bps, opposite sign)
    earnings_tilt_bps: float = 30.0  # stock value drift per quarter per 1 pp output gap
    taylor_pi: float = 0.5
    taylor_y: float = 0.5
    smoothing: float = 0.5  # weight on last quarter's rate in the Taylor rule
    # oil supply shocks (off by default): pp of inflation, and of output gap lost, per 1% oil price rise
    oil_pass_through: float = 0.0
    oil_output: float = 0.0
    oil_asset: str = "OIL"


class Economy:
    def __init__(self, fund: Fundamentals, p: EconomyParams, rng: np.random.Generator) -> None:
        self.fund, self.p, self.rng = fund, p, rng
        self.pi, self.y, self.i = p.pi0, p.y0, p.i0
        self.history: list[dict] = []  # one row per quarter
        self.pending_rate: float | None = None  # set by an AI central bank during its review
        self.statement: str | None = None
        self._oil = fund.names.index(p.oil_asset) if (p.oil_pass_through or p.oil_output) and p.oil_asset in fund.names else None
        self._oil_last = float(fund.log_v[self._oil]) if self._oil is not None else 0.0

    def taylor(self) -> float:
        p = self.p
        rule = p.r_star + self.pi + p.taylor_pi * (self.pi - p.pi_target) + p.taylor_y * self.y
        return max(0.0, round((p.smoothing * self.i + (1 - p.smoothing) * rule) * 4) / 4)

    def advance(self, quarter: int, drawdown_pct: float) -> dict:
        """End of a quarter: macro data for it are released."""
        p = self.p
        oil = 0.0  # the oil price's change over the quarter, %
        if self._oil is not None:
            now = float(self.fund.log_v[self._oil])
            oil, self._oil_last = (now - self._oil_last) * 100, now
        self.y = (p.rho_y * self.y - p.a * (self.i - p.r_star - self.pi) - p.wealth * drawdown_pct
                  - p.oil_output * oil + self.rng.normal() * p.sd_y)  # fmt: skip
        self.pi = (p.rho_pi * self.pi + (1 - p.rho_pi) * p.pi_target + p.b * self.y + p.oil_pass_through * oil
                   + self.rng.normal() * p.sd_pi)  # fmt: skip
        row = {"quarter": quarter, "inflation": round(self.pi, 2), "output_gap": round(self.y, 2),
               "rate": self.i, "taylor_rule": self.taylor(), "market_drawdown_pct": round(drawdown_pct, 2),
               **({"oil_price_change_pct": round(oil, 1)} if self._oil is not None else {})}  # fmt: skip
        self.history.append(row)
        return row

    def set_rate(self, new: float) -> float:
        """Apply a rate decision: stocks reprice at once (duration), and the earnings drift follows
        the output gap. Returns the size of the repricing in bps."""
        p = self.p
        new = float(np.clip(round(new * 4) / 4, 0.0, 15.0))
        shock = -p.duration_bps * (new - self.i) + p.earnings_tilt_bps * self.y
        self.fund.shock({n: shock for n in self.fund.names})
        self.history[-1]["decision"] = new
        self.i = new
        return shock

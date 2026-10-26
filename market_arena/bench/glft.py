"""Optimal single-maker quotes (Gueant-Lehalle-Fernandez-Tapia asymptotics of Avellaneda-Stoikov).

Calibrate from background flow:
    sigma : mid volatility per sqrt(step), estimated at a 10-step lag to wash out bid-ask bounce
    A, k  : fill intensity lambda(delta) = A exp(-k delta) for a quote delta from the mid,
            estimated from how far aggressive flow sweeps from the step's starting mid.
Closed form, with q in units of the order size:
    delta_b(q) = c + (2q+1)/2 w,  delta_a(q) = c - (2q-1)/2 w
    c = (1/gamma) ln(1 + gamma/k),  w = sqrt(sigma^2 gamma / (2kA) (1 + gamma/k)^(1 + k/gamma))
so half-spread = c + w/2 and the reservation price shifts by w per unit of inventory.

Adverse selection: if each fill is followed on average by an adverse mid move alpha (cents per
lot), the maker's reward per fill is delta - alpha. Substituting delta' = delta - alpha gives the
standard problem with A' = A exp(-k alpha), so every benchmark quote shifts out by exactly alpha.
alpha is calibrated as the volume-weighted 50-step mid move after aggressive orders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..agents.maker import MakerPolicy


@dataclass
class Calibration:
    A: float
    k: float
    sigma: float
    deltas: list[float]
    rates: list[float]
    alpha: float = 0.0  # adverse selection per lot (cents)

    @property
    def A_eff(self) -> float:
        return self.A * math.exp(-self.k * self.alpha)


def calibrate(
    mids: np.ndarray, sweeps_up: np.ndarray, sweeps_down: np.ndarray, max_delta: int = 30,
    tick: int = 1, signed_volume: np.ndarray | None = None, horizon: int = 50,
) -> Calibration:
    """mids: mid at the start of each step. sweeps_up/down: furthest distance from that mid
    reached by aggressive buys/sells in the step (0 if none)."""
    lag = 10
    sigma = float(np.std(mids[lag:] - mids[:-lag]) / math.sqrt(lag))
    # on a coarse tick grid, fill rates only change at tick multiples
    deltas = np.arange(tick, max(max_delta, 6 * tick) + 1, tick, dtype=float)
    n = len(sweeps_up)
    rates = np.array(
        [((sweeps_up >= d).sum() + (sweeps_down >= d).sum()) / (2 * n) for d in deltas]
    )
    ok = rates > 0
    slope, intercept = np.polyfit(deltas[ok], np.log(rates[ok]), 1)
    alpha = 0.0
    if signed_volume is not None:
        sv = signed_volume[:-horizon]
        move = mids[horizon:] - mids[:-horizon]
        alpha = max(0.0, float((sv * move).sum() / max(np.abs(sv).sum(), 1)))
    return Calibration(
        float(math.exp(intercept)), float(-slope), sigma, deltas.tolist(), rates.tolist(), alpha
    )


def glft_policy(cal: Calibration, gamma: float, size: int = 2, **kw) -> MakerPolicy:
    A, k, s = cal.A_eff, cal.k, cal.sigma
    c = cal.alpha + math.log1p(gamma / k) / gamma
    w = math.sqrt(s * s * gamma / (2 * k * A) * (1 + gamma / k) ** (1 + k / gamma))
    return MakerPolicy(
        half_spread=min(100.0, max(0.5, c + w / 2)), skew=min(20.0, w / size), size=size, **kw
    )

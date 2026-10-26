"""Optimal single-maker quotes (Gueant-Lehalle-Fernandez-Tapia asymptotics of Avellaneda-Stoikov).

Calibrate from background flow:
    sigma : mid volatility per sqrt(step), estimated at a 10-step lag to wash out bid-ask bounce
    A, k  : fill intensity lambda(delta) = A exp(-k delta) for a quote delta from the mid,
            estimated from how far aggressive flow sweeps from the step's starting mid.
Closed form, with q in units of the order size:
    delta_b(q) = c + (2q+1)/2 w,  delta_a(q) = c - (2q-1)/2 w
    c = (1/gamma) ln(1 + gamma/k),  w = sqrt(sigma^2 gamma / (2kA) (1 + gamma/k)^(1 + k/gamma))
so half-spread = c + w/2 and the reservation price shifts by w per unit of inventory.
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


def calibrate(
    mids: np.ndarray, sweeps_up: np.ndarray, sweeps_down: np.ndarray, max_delta: int = 30
) -> Calibration:
    """mids: mid at the start of each step. sweeps_up/down: furthest distance from that mid
    reached by aggressive buys/sells in the step (0 if none)."""
    lag = 10
    sigma = float(np.std(mids[lag:] - mids[:-lag]) / math.sqrt(lag))
    deltas = np.arange(1, max_delta + 1, dtype=float)
    n = len(sweeps_up)
    rates = np.array(
        [((sweeps_up >= d).sum() + (sweeps_down >= d).sum()) / (2 * n) for d in deltas]
    )
    ok = rates > 0
    slope, intercept = np.polyfit(deltas[ok], np.log(rates[ok]), 1)
    return Calibration(float(math.exp(intercept)), float(-slope), sigma, deltas.tolist(), rates.tolist())


def glft_policy(cal: Calibration, gamma: float, size: int = 2, **kw) -> MakerPolicy:
    A, k, s = cal.A, cal.k, cal.sigma
    c = math.log1p(gamma / k) / gamma
    w = math.sqrt(s * s * gamma / (2 * k * A) * (1 + gamma / k) ** (1 + k / gamma))
    return MakerPolicy(half_spread=max(0.5, c + w / 2), skew=w / size, size=size, **kw)

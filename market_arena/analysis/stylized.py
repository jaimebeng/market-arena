"""Stylised facts of returns: do AI-populated markets look like real ones?

Real markets show (Cont 2001): near-zero autocorrelation of returns beyond very short lags,
heavy tails (excess kurtosis, Hill tail index around 3), and volatility clustering (slowly
decaying autocorrelation of absolute returns).
"""

from __future__ import annotations

import numpy as np


def acf(x: np.ndarray, lags: int) -> list[float]:
    x = x[np.isfinite(x)]
    x = x - x.mean()
    v = (x * x).sum()
    return [round(float((x[:-k] * x[k:]).sum() / v), 4) for k in range(1, lags + 1)] if v else []


def hill(x: np.ndarray, frac: float = 0.05) -> float | None:
    a = np.sort(np.abs(x[np.isfinite(x)]))[::-1]
    k = max(10, int(len(a) * frac))
    if len(a) <= k or a[k] <= 0:
        return None
    return round(float(1 / np.mean(np.log(a[:k] / a[k]))), 3)


def stylized_facts(mid: np.ndarray, horizon: int = 10) -> dict:
    """Facts for log returns sampled every `horizon` steps."""
    m = mid[np.isfinite(mid)][::horizon]
    r = np.diff(np.log(m))
    if len(r) < 100:
        return {}
    z = (r - r.mean()) / r.std()
    return {
        "horizon_steps": horizon,
        "excess_kurtosis": round(float((z**4).mean() - 3), 3),
        "hill_tail_index": hill(r),
        "acf_returns": acf(r, 20),
        "acf_abs_returns": acf(np.abs(r), 50),
    }

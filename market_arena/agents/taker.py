"""Market taker: runs strategy code `signal(obs) -> {asset: target in [-1, 1]}` with market orders.

The same Obs object and execution rules are used live, in backtests and in the OOS gate, so a
strategy behaves identically everywhere (up to the live market reacting to its own orders).
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel
from scipy.stats import spearmanr

from ..sim.book import BUY, SELL
from ..sim.exchange import Exchange
from ..sim.history import PUBLIC_FIELDS, MarketHistory
from .sandbox import SandboxError, load_function, time_limit

FWD = 50  # forward-return horizon (steps) for the information coefficient


class TakerParams(BaseModel):
    eval_every: int = 10  # steps between signal() calls
    max_position: int = 20  # lots per asset at target = +-1
    max_order: int = 2  # lots per asset per step
    call_ms: float = 50.0  # CPU limit per signal() call


class Obs:
    """What a strategy sees. History only up to (not including) the current step."""

    FIELDS = PUBLIC_FIELDS

    def __init__(self, hist: MarketHistory, end: int, position: dict, state: dict, meta: dict):
        self._h, self._end = hist, end
        self.t = end
        self.assets = list(hist.assets)
        self.position = dict(position)
        self.state = state
        self.meta = meta

    def hist(self, asset: str, field: str, n: int) -> np.ndarray:
        if field not in self.FIELDS:
            raise KeyError(f"unknown field {field!r}; available: {self.FIELDS}")
        arr = self._h.data[asset][field][max(0, self._end - int(n)) : self._end].copy()
        return arr

    def last(self, asset: str, field: str) -> float:
        a = self.hist(asset, field, 1)
        return float(a[-1]) if len(a) else math.nan


def call_signal(fn, obs: Obs, ms: float) -> dict[str, float]:
    with time_limit(ms / 1000):
        out = fn(obs)
    if not isinstance(out, dict):
        raise SandboxError(f"signal must return a dict of asset -> target, got {type(out).__name__}")
    res = {}
    for a, v in out.items():
        if a in obs.assets:
            v = float(v)
            res[a] = 0.0 if not math.isfinite(v) else max(-1.0, min(1.0, v))
    return res


def backtest(
    code: str, hist: MarketHistory, start: int, end: int, p: TakerParams, meta: dict,
    taker_fee_bps: float = 0.0,
) -> dict:  # fmt: skip
    """Replay a strategy on recorded history [start, end). Executes at the previous step's touch
    (buy at ask, sell at bid), capped at max_order per step; marks at the mid."""
    fn = load_function(code, "signal")
    assets = hist.assets
    d = hist.data
    pos = {a: 0 for a in assets}
    target = {a: 0.0 for a in assets}
    state: dict = {}
    cash, traded = 0.0, 0
    start = max(start, 1)
    equity = np.zeros(max(end - start, 1))
    sig_t, sig_v, fwd = [], [], []
    errors = 0
    for i in range(start, end):
        if (i - start) % p.eval_every == 0:
            try:
                target.update(call_signal(fn, Obs(hist, i, pos, state, meta), p.call_ms))
            except Exception as e:  # noqa: BLE001 - surface any strategy failure to the agent
                errors += 1
                if errors >= 3:
                    raise SandboxError(f"signal() failed at step {i}: {type(e).__name__}: {e}")
            for a in assets:
                if i + FWD < end:
                    sig_t.append(i)
                    sig_v.append(target[a])
                    fwd.append(d[a]["mid"][i + FWD] / d[a]["mid"][i] - 1)
        for a in assets:
            delta = round(target[a] * p.max_position) - pos[a]
            if delta == 0:
                continue
            q = min(abs(delta), p.max_order)
            px = d[a]["ask"][i - 1] if delta > 0 else d[a]["bid"][i - 1]
            if not math.isfinite(px):
                continue
            side = 1 if delta > 0 else -1
            cash -= side * q * px + q * px * taker_fee_bps * 1e-4
            pos[a] += side * q
            traded += q
        equity[i - start] = cash + sum(pos[a] * d[a]["mid"][i] for a in assets)
    return {
        **perf_stats(equity, traded, end - start),
        "ic": _ic(sig_v, fwd),
        "signals": np.array(sig_v),
        "errors": errors,
    }


def perf_stats(equity: np.ndarray, traded: int, n: int, block: int = 100) -> dict:
    blocks = np.diff(equity[::block]) if len(equity) > block else np.array([0.0])
    sd = blocks.std()
    return {
        "pnl": round(float(equity[-1]), 1),
        # Sharpe of 100-step P&L blocks, scaled to one 2,000-step epoch
        "sharpe": round(float(blocks.mean() / sd * math.sqrt(2000 / block)), 2) if sd > 0 else 0.0,
        "max_drawdown": round(float((np.maximum.accumulate(equity) - equity).max()), 1),
        "turnover": round(traded / max(n, 1), 3),
    }


def _ic(sig: list[float], fwd: list[float]) -> float:
    s, f = np.asarray(sig), np.asarray(fwd)
    ok = np.isfinite(s) & np.isfinite(f)
    if ok.sum() < 20 or np.std(s[ok]) == 0:
        return 0.0
    return round(float(spearmanr(s[ok], f[ok]).statistic), 4)


class StrategyTaker:
    """Executes a strategy live in the arena."""

    role = "taker"

    def __init__(self, agent_id: str, assets: list[str], arena, params: dict | None = None):
        self.id = agent_id
        self.assets = assets
        self.arena = arena
        self.p = TakerParams(**(params or {}))
        self.model: str | None = None
        self.code: str | None = None
        self.name: str | None = None
        self.fn = None
        self.state: dict = {}
        self.target = {a: 0.0 for a in arena.assets}
        self.errors: list[str] = []

    @property
    def policies(self):  # takers have no maker policy; keeps arena code uniform
        return {}

    def install(self, code: str, name: str) -> None:
        self.fn = load_function(code, "signal")
        self.code, self.name = code, name
        self.state = {}
        self.errors = []

    def on_step(self, ex: Exchange) -> None:
        acct = ex.accounts[self.id]
        if self.fn is not None and ex.t % self.p.eval_every == 0:
            obs = Obs(self.arena.hist, self.arena.hist.n, acct.pos, self.state, self.arena.public_meta)
            try:
                self.target.update(call_signal(self.fn, obs, self.p.call_ms))
            except Exception as e:  # noqa: BLE001 - strategy bug: go flat, report at review
                self.errors.append(f"t={ex.t}: {type(e).__name__}: {e}")
                self.target = {a: 0.0 for a in self.target}
                if len(self.errors) >= 5:
                    self.fn = None  # disabled until the next review installs a fix
        for a in self.assets:
            delta = round(self.target.get(a, 0.0) * self.p.max_position) - acct.pos[a]
            if delta:
                ex.market(self.id, a, BUY if delta > 0 else SELL, min(abs(delta), self.p.max_order))

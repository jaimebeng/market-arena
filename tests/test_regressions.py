"""Regression tests for bugs found in the independent review."""

import asyncio
import math

import numpy as np
import pytest

from market_arena.agents.sandbox import SandboxError, load_function
from market_arena.agents.taker import Obs, call_signal
from market_arena.bench.glft import Calibration, glft_quotes
from market_arena.runner.arena import Arena
from market_arena.runner.config import AgentCfg, ArenaConfig
from market_arena.sim.history import MarketHistory


def test_strategy_cannot_unlock_hidden_fair_value():
    with pytest.raises(SandboxError):
        load_function("def signal(obs):\n    obs.FIELDS = obs.FIELDS + ('value',)\n    return {}", "signal")
    h = MarketHistory(["A"], 10)
    h.n = 5
    with pytest.raises(KeyError):
        Obs(h, 5, {}, {}, {}).hist("A", "value", 3)


def test_strategy_cannot_mutate_shared_meta():
    meta = {"index": {"name": "IDX", "shares": {"A": 1.0}}}
    fn = load_function("def signal(obs):\n    obs.meta['index'] = None\n    return {}", "signal")
    h = MarketHistory(["A"], 10)
    call_signal(fn, Obs(h, 0, {}, {}, meta), 50)
    assert meta["index"] is not None


def test_obs_positions_cover_all_assets():
    h = MarketHistory(["A", "B"], 10)
    assert Obs(h, 0, {}, {}, {}).position == {"A": 0, "B": 0}


def _run(**kw):
    cfg = ArenaConfig(name="t", n_epochs=1, steps_per_epoch=1500, calibration_steps=3000,
                      out_dir="/tmp/arena_tests", **kw)
    arena = Arena(cfg)
    asyncio.run(arena.run())
    return arena


def test_speed_bump_does_not_leak_noise_orders():
    arena = _run(rules={"min_resting_steps": 20})
    book = arena.ex.books["A"]
    stale = [o for o in book.orders.values() if o.owner == "noise" and arena.ex.t - o.t > 600]
    assert len(stale) == 0


def test_accounting_conserves_cash_and_edge_uses_pre_fill_mid():
    arena = _run(rules={"maker_fee_bps": -1.0, "taker_fee_bps": 2.0}, agents=[
        AgentCfg(id="glft", kind="glft"),
        AgentCfg(id="tk", kind="textbook_taker", params={"signal": "trade_flow"}),
    ])
    marks = {"A": arena.ex.mid("A")}
    accts = arena.ex.accounts.values()
    assert sum(a.pos["A"] for a in accts) == 0
    assert math.isclose(sum(a.equity(marks) for a in accts), -sum(a.fees for a in accts), abs_tol=1e-6)
    fills = [f for f in arena.ex.fill_log if f.owner == "glft"]
    assert fills and all(np.isfinite(f.mid_before) for f in fills)


def test_glft_lot_size_formula():
    cal = Calibration(A=0.5, k=0.3, sigma=1.3, deltas=[], rates=[])
    g, D = 0.05, 2
    hs, skew = glft_quotes(cal, g, D)
    s = math.sqrt(g * 1.3**2 / (2 * 0.5 * 0.3) * (1 + g * D / 0.3) ** (1 + 0.3 / (g * D)))
    assert math.isclose(skew, s) and math.isclose(hs, math.log1p(g * D / 0.3) / (g * D) + D * s / 2)

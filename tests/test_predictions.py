"""Prediction markets: LMSR pricing, contracts on the run's events, the crowd, settlement."""

import asyncio
import json
import math

from market_arena.runner.arena import Arena
from market_arena.runner.config import ArenaConfig
from market_arena.sim.predictions import UNIT, Contract


def test_lmsr_prices_and_payouts():
    c = Contract("x", "index_up", "?", 0, 0, b=30.0, p0=0.3)
    assert math.isclose(c.price(), 0.3, abs_tol=1e-9)
    yes, shares, cost = c.buy_to("a", 0.6, max_shares=1000)
    assert yes and math.isclose(c.price(), 0.6, abs_tol=1e-6)
    assert 0.3 * UNIT * shares < cost < 0.6 * UNIT * shares  # paid between the old and new price
    _, s2, _ = c.buy_to("b", 0.5, max_shares=5)  # a NO bet, capped by its stake
    assert s2 == 5 and 0.5 < c.price() < 0.6
    pay = c.settle(True)
    assert pay["a"] == shares * UNIT and pay["b"] == 0


def test_contracts_open_trade_and_settle(tmp_path):
    cfg = ArenaConfig.load(
        "configs/grand.yaml", out_dir=str(tmp_path), seed=9, n_epochs=3, steps_per_epoch=600, holdout=200,
        calibration_steps=2000, live_every=50, reporter=None, predictions={},
        agents=[{"id": "glft", "kind": "glft"}],
        swarm={"n": 2, "kind": "rule_investor", "personas": ["momentum"], "assets": ["A", "B", "C", "IDX"]})  # fmt: skip
    arena = Arena(cfg)
    asyncio.run(arena.run())
    pm = arena.pm
    kinds = {c.kind for c in pm.contracts}
    assert {"index_up", "liquidations", "inflation", "rate_cut"} <= kinds  # no regulator: no referral
    assert not any(c.kind == "rate_cut" and c.quarter == 2 for c in pm.contracts)  # nothing decides it
    assert all(c.outcome is not None for c in pm.contracts)  # every contract settled
    idx = [c for c in pm.contracts if c.kind == "index_up"]
    assert len(idx) == 3 and all(c.level for c in idx)
    assert any("pm_crowd" in c.pos for c in pm.contracts)  # the crowd traded
    rows = [json.loads(x) for x in open(arena.out / "live.jsonl")]
    assert sum(r["k"] == "pm_open" for r in rows) == len(pm.contracts)
    assert sum(r["k"] == "pm_resolve" for r in rows) == len(pm.contracts)
    assert any("pm" in r for r in rows if r["k"] == "f")
    meta = json.loads((arena.out / "meta.json").read_text())
    assert len(meta["predictions"]["contracts"]) == len(pm.contracts)

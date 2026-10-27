"""Overnight sessions, the liquidation engine, swarms, and the verifiable decision log."""

import asyncio
import json

import numpy as np
import pytest

from market_arena.llm import client
from market_arena.runner.arena import Arena
from market_arena.runner.config import ArenaConfig
from market_arena.runner.verify import check_chain, verify
from market_arena.sim.book import BUY, SELL
from market_arena.sim.exchange import Exchange, Rules
from market_arena.sim.perps import LiquidationEngine, LiquidationParams


def _cfg(tmp_path, **kw) -> ArenaConfig:
    return ArenaConfig.load("configs/scripted.yaml", out_dir=str(tmp_path), n_epochs=2, steps_per_epoch=400,
                            calibration_steps=2000, **kw)  # fmt: skip


def test_swarm_expands_once_and_round_trips():
    c = ArenaConfig(name="x", swarm={"n": 5, "models": ["m:a", "m:b"], "personas": ["p", "q", "r"]})
    ids = [a.id for a in c.agents]
    assert ids == ["inv_01", "inv_02", "inv_03", "inv_04", "inv_05"]
    assert [a.model for a in c.agents][:3] == ["m:a", "m:b", "m:a"]
    assert [a.params["persona"] for a in c.agents][:4] == ["p", "q", "r", "p"]
    assert len(ArenaConfig(**c.model_dump()).agents) == 5  # a saved config does not expand again


def test_closed_exchange_does_not_trade_overnight(tmp_path):
    a = Arena(_cfg(tmp_path, session={"night_trading": False}))
    asyncio.run(a.run())
    m0, m1 = a.metrics_log
    assert m0["session"] == "day" and m1["session"] == "night"
    assert m0["market"]["A"]["volume"] > 0 and m1["market"]["A"]["volume"] == 0


def test_overnight_flow_is_thinned(tmp_path):
    a = Arena(_cfg(tmp_path, session={"night_trading": True, "night_activity": 0.1}))
    asyncio.run(a.run())
    day, night = (m["market"]["A"]["volume"] for m in a.metrics_log)
    assert 0 < night < 0.4 * day


def _book() -> Exchange:
    ex = Exchange(["A"], Rules())
    ex.market_makers = {"mm"}
    for k in range(1, 40):
        ex.limit("mm", "A", BUY, 10_000 - 5 * k, 3)
        ex.limit("mm", "A", SELL, 10_000 + 5 * k, 3)
    return ex


def test_liquidation_ladder_and_adl():
    p = LiquidationParams(n_longs=4, long_lots=5, leverage_min=40, leverage_max=50, n_shorts=2, short_lots=10,
                          chunk=5, insurance_fund=0, adl=True)  # fmt: skip
    ex = _book()
    eng = LiquidationEngine(ex, p, np.random.default_rng(0))
    eng.step({}, {})
    assert eng.stats()["liquidations"] == 0
    for oid in list(ex.books["A"].orders):  # the market gaps 10% down, below every long's bankruptcy price
        ex.books["A"].cancel(oid)
    ex.limit("mm", "A", BUY, 8_995, 100)
    ex.limit("mm", "A", SELL, 9_005, 100)
    for _ in range(4):
        eng.step({}, {})
    s = eng.stats()
    assert s["liquidations"] == 4
    assert s["adl_lots"] > 0  # bankrupt positions closed against the shorts, not the book
    assert s["open_long_lots"] == 0


def test_decision_log_is_hash_chained_and_replays_identically(tmp_path):
    """A run with a scripted 'model': the replay re-executes every logged tool call and must
    reproduce the market byte for byte; editing a logged decision breaks the chain."""
    cfg = _cfg(tmp_path, agents=[{"id": "glft", "kind": "glft"},
                                 {"id": "ai_mm", "kind": "llm_maker", "model": "fake:model"}])  # fmt: skip
    recorded = [{"agent": "ai_mm", "epoch": 0, "turns": [{"calls": [
        {"name": "get_performance", "args": {}},
        {"name": "set_policy", "args": {"policies": [{"asset": "A", "half_spread": 9, "skew": 1.0}],
                                        "rationale": "widen"}}]}]}]  # fmt: skip
    client.REPLAY = client.Replay(recorded)  # stands in for the model while recording
    try:
        a = Arena(cfg)
        asyncio.run(a.run())
    finally:
        client.REPLAY = None
    assert a.agents[1].policies["A"].half_spread == 9
    run = a.out
    r = verify(run)
    assert r["verified"] and r["trades"] == "identical" and r["chain"].startswith("intact")
    decisions = [json.loads(line) for line in open(run / "decisions.jsonl")]
    decisions[0]["policy"]["A"]["half_spread"] = 5.0  # tamper with the record
    assert check_chain(decisions).startswith("BROKEN")


@pytest.mark.parametrize("text", ["tick", "rebate"])
def test_lab_levers_are_validated(text):
    from market_arena.server.lab import Levers

    with pytest.raises(ValueError):
        Levers(tick=0)
    assert Levers(maker_fee_bps=-2, taker_fee_bps=3).rules() == {"maker_fee_bps": -2, "taker_fee_bps": 3}

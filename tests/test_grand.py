"""The Grand Arena: a stochastic storyline, best-venue investors, the live stream."""

import asyncio
import json

from market_arena.agents.taker import backtest, TakerParams
from market_arena.bench.signals import TEXTBOOK
from market_arena.runner.arena import Arena
from market_arena.runner.config import ArenaConfig
from market_arena.sim.storyline import draw_storyline


def _grand(tmp_path, **kw) -> ArenaConfig:
    """The grand config with scripted agents only (rule investors, GLFT), short."""
    base = dict(out_dir=str(tmp_path), n_epochs=2, steps_per_epoch=600, holdout=200, calibration_steps=2000,
                live_every=50, agents=[{"id": "glft", "kind": "glft"}],
                swarm={"n": 4, "kind": "rule_investor", "personas": ["momentum", "noise"],
                       "assets": ["A", "B", "C", "IDX"]})  # fmt: skip
    return ArenaConfig.load("configs/grand.yaml", **{**base, **kw})


def test_storyline_is_drawn_from_the_seed(tmp_path):
    a, b, c = (draw_storyline(_grand(tmp_path, seed=s)) for s in (5, 5, 6))
    assert a.shocks == b.shocks and a.population == b.population  # same seed, same story
    assert (a.shocks, a.population.fire_sale) != (c.shocks, c.population.fire_sale)
    assert a.storyline.drawn and 1 <= len([s for s in a.shocks if s.bps]) <= 3
    again = draw_storyline(ArenaConfig(**a.model_dump()))  # a recorded config is not redrawn
    assert again.shocks == a.shocks


def test_grand_runs_and_streams_live(tmp_path):
    arena = Arena(_grand(tmp_path, seed=7))
    asyncio.run(arena.run())
    rows = [json.loads(x) for x in open(arena.out / "live.jsonl")]
    kinds = [r["k"] for r in rows]
    assert kinds[0] == "start" and kinds[-1] == "end"
    assert kinds.count("epoch") == 2 and kinds.count("f") == 2 * 600 // 50
    frame = next(r for r in rows if r["k"] == "f")
    assert set(frame["mid"]) == set(arena.assets) and "A.X" in frame["mid"]
    assert set(frame["v"]) == {"A", "B", "C", "IDX"}
    assert rows[-1]["storyline"] == [s.model_dump() for s in arena.cfg.shocks]
    # investors route each order to the best venue, so they trade on both exchanges
    pos = arena.ex.accounts
    inv = [ag for ag in arena.agents if ag.role == "investor"]
    venues = {v for ag in inv for v in ("A", "A.X", "B", "B.X", "C", "C.X") if pos[ag.id].pos[v]}
    assert any(v.endswith(".X") for v in venues) and any("." not in v for v in venues)
    assert all(ag._position(arena.ex, "A") == pos[ag.id].pos["A"] + pos[ag.id].pos["A.X"] for ag in inv)
    # the venue-arbitrage benchmark runs on the multi-exchange tape
    r = backtest(TEXTBOOK["venue_arbitrage"], arena.hist, 100, arena.hist.n, TakerParams(), arena.public_meta)
    assert r["errors"] == 0 and r["turnover"] > 0


def test_macro_shock_moves_every_stock(tmp_path):
    cfg = _grand(tmp_path, seed=3, storyline=None, n_epochs=1,
                 shocks=[{"at_step": 100, "asset": "*", "bps": -300, "headline": "macro"}])  # fmt: skip
    arena = Arena(cfg)
    asyncio.run(arena.run())
    v = arena.hist.get
    for a in ("A", "B", "C"):
        assert v(a, "value", 101, 102)[0] / v(a, "value", 99, 100)[0] < 0.985

"""Grand Arena additions: the regulator's conduct tool, stub quotes, a forum crowd, the AI reporter's
plumbing, and the analyst's view of a run (cut at the playhead)."""

import asyncio
import json
import sys
from pathlib import Path

import numpy as np

from market_arena.agents.analyst import RunView
from market_arena.agents.reporter import MarketReporter, _parse
from market_arena.agents.surveillance import _corr, maker_conduct
from market_arena.llm import client
from market_arena.runner.arena import Arena
from market_arena.runner.config import ArenaConfig, ReporterCfg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from export_grand import place_commentary  # noqa: E402

SCRIPTED = dict(n_epochs=1, steps_per_epoch=600, holdout=200, calibration_steps=2000, live_every=50,
                agents=[{"id": "glft", "kind": "glft"}], swarm=None, reporter=None)  # fmt: skip


def test_maker_conduct_reports_each_maker(tmp_path):
    cfg = ArenaConfig.load("configs/grand.yaml", out_dir=str(tmp_path), seed=3, storyline=None,
                           **{**SCRIPTED, "n_epochs": 3})  # fmt: skip
    arena = Arena(cfg)
    asyncio.run(arena.run())
    out = maker_conduct(arena)
    g = out["makers"]["glft"]
    assert len(g["quoted_half_spread_by_epoch"]) == 3 and g["chat_messages"] == 0
    assert g["avg_inventory_skew"] > 0  # GLFT leans its quotes against its inventory
    assert g["spread_change_corr_with_rivals"] is None  # no rival maker to move with
    assert _corr([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0 and _corr([1, 2], [1, 2]) is None


def _fund_low(tmp_path, stubs):
    cfg = ArenaConfig.load("configs/scenarios/flash_crash.yaml", out_dir=str(tmp_path), seed=4, shocks=[],
                           zi={"stub_bps": stubs}, **SCRIPTED,
                           population={"fire_sale": {"at_step": 200, "asset": "IDX", "qty": 1500, "over": 30}})  # fmt: skip
    arena = Arena(cfg)
    asyncio.run(arena.run())
    fills = [f for f in arena.ex.fill_log if f.owner == "fund_liquidation"]
    return min(f.price for f in fills) / fills[0].mid_before


def test_stub_quotes_catch_an_emptied_book(tmp_path):
    # with no stub bids, a sale that empties the book cannot print far below the market;
    # with stub bids (as in May 2010) it trades down to them
    assert _fund_low(tmp_path / "a", [300, 600]) < 0.96 < _fund_low(tmp_path / "b", [])


def test_forum_crowd_posts_and_buys(tmp_path):
    camp = {"asset": "B", "start": 100, "end": 400, "every": 50, "stance": 0.9, "buy_rate": 2.0}
    cfg = ArenaConfig.load("configs/scenarios/meme_squeeze.yaml", out_dir=str(tmp_path), seed=5, shocks=[],
                           **SCRIPTED, population={"retail": {"rate": 0.1, "herd": 0.5}, "forum_campaign": camp})  # fmt: skip
    arena = Arena(cfg)
    asyncio.run(arena.run())
    posts = [p for p in arena.forum if p["agent"] == "forum_crowd"]
    assert len(posts) == 6 and all(p["asset"] == "B" and p["stance"] == 0.9 for p in posts)
    bought = sum(f.side * f.qty for f in arena.ex.fill_log if f.owner == "retail" and f.asset.startswith("B")
                 and 100 <= f.t < 400)  # fmt: skip
    assert bought > 300


def test_reporter_parsing_and_replay(tmp_path):
    assert _parse("HEADLINE: Cobalt plunges\nBODY: It fell 4%.\nMore.") == ("Cobalt plunges", "It fell 4%. More.")
    assert _parse("**HEADLINE:** Rates cut\n**BODY:** The bank cut.") == ("Rates cut", "The bank cut.")
    assert _parse("Just a line\nand a body") == ("Just a line", "and a body")
    cfg = ArenaConfig.load("configs/grand.yaml", out_dir=str(tmp_path), **SCRIPTED)
    arena = Arena(cfg)
    client.REPLAY = client.Replay([])
    try:  # replaying a run re-executes trades, not commentary
        assert not MarketReporter(ReporterCfg(model="meta:x"), arena).enabled
    finally:
        client.REPLAY = None


def test_commentary_is_placed_at_its_moment():
    lines = [{"k": "start"}, *({"k": "f", "t": t} for t in (50, 100, 150)),
             {"k": "commentary", "t": 60, "kind": "breaking"}, {"k": "epoch", "t": 150},
             {"k": "commentary", "t": 150, "kind": "wrap"}, {"k": "end", "t": 150}]  # fmt: skip
    out = place_commentary(lines)
    assert len(out) == len(lines)
    assert [x["k"] for x in out] == ["start", "f", "f", "commentary", "f", "commentary", "epoch", "end"]


def test_analyst_sees_only_up_to_the_playhead():
    lines = json.loads(Path("web/public/grand/grand_s352217.json").read_text())["lines"]
    v = RunView(lines, upto=3000)
    assert all(x.get("t", 0) <= 3000 for x in v.lines) and not any(x["k"] == "end" for x in v.lines)
    o = v.overview()
    assert o["step_now"] == 3000 and o["quarter_now"] == 3 and "maker_glimmer" in o["participants"]
    p = v.price_history({"asset": "C"})
    assert p["points"][-1]["t"] <= 3000 and p["low"]["mid"] <= p["high"]["mid"]
    board = v.leaderboard({})
    assert [r["equity"] for r in board] == sorted((r["equity"] for r in board), reverse=True)
    assert all(d["epoch"] == 0 for d in v.decisions({"epoch": 0}) if "epoch" in d)
    assert np.all([e["t"] <= 3000 for e in v.events({}) if "t" in e])

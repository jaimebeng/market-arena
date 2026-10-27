"""The LLM red team: tactic validation, the review loop and the debrief (LLM calls stubbed)."""

import asyncio

import pytest

from market_arena.agents import red_team
from market_arena.agents.red_team import check_tactics, fake_lots_per_epoch
from market_arena.agents.spoofer import SpoofParams
from market_arena.llm.client import Transcript
from market_arena.runner.arena import Arena
from market_arena.runner.config import AgentCfg, ArenaConfig

LAYERED = {"spoof_size": 30, "layers": 3, "hold": 8, "cycle": 30, "bait_size": 2,
           "rationale": "smaller orders over three levels, held past the fast-cancel window"}  # fmt: skip


def test_check_tactics():
    cur = SpoofParams()
    p = check_tactics(LAYERED, cur, 2000, 1500)
    assert (p.layers, p.hold) == (3, 8)
    assert fake_lots_per_epoch(p, 2000) == 2000
    with pytest.raises(ValueError, match="mandate"):
        check_tactics(LAYERED | {"cycle": 100}, cur, 2000, 1500)
    with pytest.raises(ValueError, match="hold"):
        check_tactics(LAYERED | {"hold": 30}, cur, 2000, 1500)
    with pytest.raises(ValueError, match="layers"):
        check_tactics(LAYERED | {"layers": 9}, cur, 2000, 1500)
    with pytest.raises(ValueError, match="bait_ttl"):
        check_tactics(LAYERED | {"bait_ttl": 40}, cur, 2000, 1500)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    calls = []

    async def fake_run_tools(model, system, user, tools, handlers, terminal, **kw):
        tr = Transcript(model=model)
        for name in ("get_my_footprint", "get_my_cancel_fill_pattern", "get_debrief"):
            calls.append((name, handlers[name]({})))
        try:  # below the mandate: rejected, the model would retry
            handlers[terminal](LAYERED | {"cycle": 150})
        except ValueError as e:
            calls.append(("rejected", str(e)))
        handlers[terminal](LAYERED)
        tr.final = LAYERED
        return tr

    mp = pytest.MonkeyPatch()
    mp.setattr(red_team, "run_tools", fake_run_tools)
    cfg = ArenaConfig(
        name="rt", n_epochs=3, steps_per_epoch=1500, calibration_steps=3000,
        out_dir=str(tmp_path_factory.mktemp("rt")),
        agents=[
            AgentCfg(id="glft", kind="glft"),
            AgentCfg(id="mm", kind="static_maker", params={"half_spread": 4}),
            AgentCfg(id="trader_b", kind="llm_red_team", model="meta:test",
                     params={"mandate_lots": 1000}),
        ],
    )  # fmt: skip
    arena = Arena(cfg)
    asyncio.run(arena.run())
    mp.undo()
    return arena, calls


def test_red_team_adapts_its_footprint(run):
    arena, calls = run
    rt = next(ag for ag in arena.agents if ag.id == "trader_b")
    assert rt.p.layers == 3 and rt.p.hold == 8
    assert all(f > 0 for f in rt.fake_by_epoch)
    assert any(name == "rejected" and "mandate" in msg for name, msg in calls)
    me = [m["orders"]["trader_b"] for m in arena.metrics_log]
    size = [o["cancelled_qty"] / o["cancelled"] for o in me]
    fast = [o["fast_cancels"] / o["cancelled"] for o in me]
    # epoch 0 runs the scripted defaults (25-lot fakes cancelled after 4 steps), epoch 2 the
    # layered plan (10-lot fakes held for 8 steps): smaller cancels, no fast cancels
    assert size[2] < size[0] / 1.5
    assert fast[0] > 0.5 and fast[2] < 0.2


def test_debrief_only_shows_earlier_reports(run):
    arena, _ = run
    rt = next(ag for ag in arena.agents if ag.id == "trader_b")

    class Reg:
        role, id = "regulator", "reg"
        reports = [
            {"epoch": 0, "findings": [{"agent": "trader_b", "conduct": "spoofing",
                                       "severity": "warning", "evidence": "big cancels"}]},
            {"epoch": 1, "findings": [{"agent": "trader_b", "conduct": "spoofing",
                                       "severity": "referral", "evidence": "again"}]},
        ]  # fmt: skip

    arena.agents.append(Reg())
    try:
        d = rt._debrief(arena, 1)
    finally:
        arena.agents.pop()
    assert d["regulator_present"]
    assert [f["severity"] for f in d["findings_about_you"]] == ["warning"]

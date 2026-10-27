"""Surveillance data, the planted spoofer, and the makers' chat plumbing (no LLM calls)."""

import asyncio

import pytest

from market_arena.agents.llm_maker import TOOLS, _with_chat
from market_arena.agents.surveillance import LLMSurveillance
from market_arena.runner.arena import Arena
from market_arena.runner.config import AgentCfg, ArenaConfig


@pytest.fixture(scope="module")
def arena():
    cfg = ArenaConfig(
        name="surv", n_epochs=2, steps_per_epoch=1500, calibration_steps=3000,
        out_dir="/tmp/arena_tests",
        agents=[
            AgentCfg(id="glft", kind="glft"),
            AgentCfg(id="mm", kind="static_maker", params={"half_spread": 4, "skew": 0.5}),
            AgentCfg(id="imb", kind="textbook_taker",
                     params={"signal": "order_book_imbalance", "max_order": 1}),
            AgentCfg(id="spoofer", kind="spoofer"),
        ],
    )  # fmt: skip
    a = Arena(cfg)
    asyncio.run(a.run())
    return a


def test_background_flow_is_not_tracked(arena):
    owners = {c[1] for c in arena.ex.cancel_log}
    assert owners <= {"glft", "mm", "imb", "spoofer"}
    assert set(arena.metrics_log[-1]["orders"]) <= {"glft", "mm", "imb", "spoofer"}


def test_spoofer_stands_out_from_honest_makers(arena):
    s = LLMSurveillance("reg", arena.assets, "meta:x")
    act = s._order_activity(arena)[-1]["participants"]
    spoof, mm = act["spoofer"], act["mm"]
    assert spoof["avg_cancelled_size"] > 5 * mm["avg_cancelled_size"]
    m = arena.metrics_log[-1]
    pat = s._cancel_fill_pattern(arena, "spoofer", m["t0"], m["t1"])
    assert pat["fills"] > 0
    assert pat["avg_size_of_paired_opposite_cancels"] > 5 * pat["avg_fill_size"]


def test_file_report_validates_names(arena):
    s = LLMSurveillance("reg", arena.assets, "meta:x")
    s._arena = arena
    with pytest.raises(ValueError):
        s._file_report({"findings": [{"agent": "ghost", "conduct": "spoofing", "severity": "watch"}]})
    assert s._file_report({"findings": [], "summary": "clean"})["ok"]


def test_chat_field_only_when_enabled():
    tools = _with_chat(TOOLS)
    sp = next(t for t in tools if t["function"]["name"] == "set_policy")
    assert "message" in sp["function"]["parameters"]["properties"]
    orig = next(t for t in TOOLS if t["function"]["name"] == "set_policy")
    assert "message" not in orig["function"]["parameters"]["properties"]


def test_post_chat_records(arena):
    arena._files["chat"] = open(arena.out / "chat_test.jsonl", "w")
    arena.post_chat(0, "reg", "Reminder: coordination is illegal.", kind="notice")
    assert arena.chat[-1]["kind"] == "notice"

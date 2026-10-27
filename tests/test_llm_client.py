"""LLM client caching across event loops (no network calls)."""

import asyncio

from market_arena.llm import client


def test_client_is_per_event_loop(monkeypatch):
    # a reused worker process runs several arenas, each in its own asyncio.run (a new loop);
    # a client bound to a closed loop fails with "Event loop is closed"
    monkeypatch.setenv("META_BASE_URL", "http://localhost:9/v1")
    monkeypatch.setenv("META_API_KEY", "test")
    monkeypatch.setattr(client, "_clients", {})

    async def get_twice():
        return client.client_for("meta"), client.client_for("meta")

    a1, a2 = asyncio.run(get_twice())
    b1, _ = asyncio.run(get_twice())
    assert a1 is a2  # reused within one loop
    assert b1 is not a1  # fresh client on a new loop

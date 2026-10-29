"""Freeze one market moment for the "Attack the AI traders" page (server/attack.py).

    python scripts/attack_snapshot.py   # writes runs/attack/snapshot.json

Replays the prompt-injection market's control run (runs/injection/baseline/s703, no plant) to the
end of epoch 3, answering every review from its log, and records what each AI investor saw at
that review: its system prompt, its user message, its tool list and every tool's full output.
A visitor's plant is then added to that moment's newswire or forum, and the investors review it
live (server/attack.py), so every attack faces the same market.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_arena.agents import llm_investor  # noqa: E402
from market_arena.llm import client  # noqa: E402
from market_arena.runner.arena import Arena  # noqa: E402
from market_arena.runner.config import ArenaConfig  # noqa: E402

RUN = ROOT / "runs" / "injection" / "baseline" / "s703"
EPOCH = 3  # a calm moment: every investor flat in C, only mild news about it
READS = ("get_news", "get_prices", "get_portfolio", "get_forum")


def main() -> None:
    meta = json.loads((RUN / "meta.json").read_text())
    decisions = [json.loads(line) for line in open(RUN / "decisions.jsonl")]
    shots: dict[str, dict] = {}
    recorded = llm_investor.run_tools

    async def capture(model, system, user, tools, handlers, terminal, **kw):
        agent = client.CURRENT_AGENT.get()
        epoch = int(user.split()[1])
        if epoch == EPOCH and agent not in shots:
            shots[agent] = {"agent": agent, "model": model, "system": system, "user": user, "tools": tools,
                            "results": {k: handlers[k]({}) for k in READS}}  # fmt: skip
        return await recorded(model, system, user, tools, handlers, terminal, **kw)

    llm_investor.run_tools = capture
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ArenaConfig(**{**meta["config"], "out_dir": tmp})
        client.REPLAY = client.Replay(decisions)
        try:
            arena = Arena(cfg)
            asyncio.run(arena.run())
        finally:
            client.REPLAY = None
            llm_investor.run_tools = recorded
    spe = meta["config"]["steps_per_epoch"]
    inj = next(a for a in meta["config"]["agents"] if a["kind"] == "injector")
    out = {"run": str(RUN.relative_to(ROOT)), "epoch": EPOCH, "plant_t": (EPOCH + 1) * spe - 300,
           "review_t": (EPOCH + 1) * spe, "asset": inj["params"]["asset"], "lots": inj["params"].get("lots", 37),
           "attacker": inj["id"], "investors": [shots[k] for k in sorted(shots)]}  # fmt: skip
    dest = ROOT / "runs" / "attack" / "snapshot.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, default=str))
    print("wrote", dest.relative_to(ROOT), len(out["investors"]), "investors")


if __name__ == "__main__":
    main()

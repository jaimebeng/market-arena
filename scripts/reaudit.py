"""Re-audit recorded markets with the regulator before and after a change (RESULTS §24).

    python scripts/reaudit.py runs/grand/s559705   # writes runs/reaudit/grand_s559705.json

The run is replayed exactly, every AI review answered from its log as in `runner.verify`. At each
quarter-end two shadow regulators also audit the replayed market, with live model calls: the
regulator as it was ("before": no get_maker_conduct, no coordination rule) and the fixed one
("after"). Shadows post and log nothing, so the market stays the recorded one and the two audits
are paired on identical histories.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from market_arena.agents import surveillance  # noqa: E402
from market_arena.llm import client  # noqa: E402
from market_arena.runner.arena import Arena  # noqa: E402
from market_arena.runner.config import ArenaConfig  # noqa: E402

VERSIONS = {"before": False, "after": True}  # shadow name -> conduct_tool


def reaudit(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "meta.json").read_text())
    decisions = [json.loads(line) for line in open(run_dir / "decisions.jsonl")]
    regs = [d for d in decisions if d.get("role") == "regulator"]
    shadows = {k: surveillance.LLMSurveillance(regs[0]["agent"], [], regs[0]["model"], {"conduct_tool": v})
               for k, v in VERSIONS.items()}  # fmt: skip
    cost = {k: 0.0 for k in shadows}
    recorded_review = surveillance.LLMSurveillance.review

    async def review(self, arena, epoch, m):
        await recorded_review(self, arena, epoch, m)  # answered from the log
        token = client.BYPASS_REPLAY.set(True)
        try:
            trs = await asyncio.gather(*(s.audit(arena, epoch, m) for s in shadows.values()))
        finally:
            client.BYPASS_REPLAY.reset(token)
        for k, tr in zip(shadows, trs):
            cost[k] += tr.cost or 0
        print(f"{run_dir.name} epoch {epoch}: " + ", ".join(
            f"{k} {[(f['agent'], f['conduct'], f['severity']) for f in s.reports[-1]['findings']]}"
            for k, s in shadows.items()), flush=True)  # fmt: skip

    surveillance.LLMSurveillance.review = review
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ArenaConfig(**{**meta["config"], "out_dir": tmp})
        client.REPLAY = client.Replay(decisions)
        try:
            asyncio.run(Arena(cfg).run())
        finally:
            client.REPLAY = None
            surveillance.LLMSurveillance.review = recorded_review
    epochs = []
    for i, r in enumerate(regs):
        epochs.append({"epoch": r["epoch"], "recorded": r.get("findings") or [],
                       **{k: s.reports[i]["findings"] for k, s in shadows.items()}})  # fmt: skip
    return {"run": str(run_dir.relative_to(ROOT)), "model": regs[0]["model"],
            "cost": {k: round(v, 4) for k, v in cost.items()}, "epochs": epochs}  # fmt: skip


if __name__ == "__main__":
    run = Path(sys.argv[1]).resolve()
    out = ROOT / "runs" / "reaudit" / f"{run.parent.name}_{run.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reaudit(run), indent=1))
    print("wrote", out.relative_to(ROOT))

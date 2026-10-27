"""Verify a recorded run without calling any model.

    python -m market_arena.runner.verify runs/stress/baseline/s121 [more run dirs...]

1. Hash chain: each decision record carries the hash of the previous one, so an edited, inserted
   or deleted decision breaks the chain (runs recorded before the chain was added are skipped).
2. Replay: the market is re-executed from the config and seed, and every AI review is answered
   from the log: each logged tool call is made again, with the same arguments, against the live
   replayed market. The simulator is deterministic, so if the log is complete and honest the
   replay reproduces every trade. Trades and order-book snapshots are compared byte for byte.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

from ..llm import client
from .arena import GENESIS, Arena, file_sha256, record_hash
from .config import ArenaConfig


def check_chain(decisions: list[dict]) -> str:
    if not decisions or "hash" not in decisions[0]:
        return "not recorded (run predates the hash chain)"
    prev = GENESIS
    for i, d in enumerate(decisions):
        if d.get("prev_hash") != prev or record_hash(d) != d["hash"]:
            return f"BROKEN at decision {i} ({d.get('agent')}, epoch {d.get('epoch')})"
        prev = d["hash"]
    return f"intact ({len(decisions)} decisions, head {prev[:12]})"


def verify(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "meta.json").read_text())
    decisions = [json.loads(line) for line in open(run_dir / "decisions.jsonl")]
    out = {"run": str(run_dir), "chain": check_chain(decisions)}
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ArenaConfig(**{**meta["config"], "out_dir": tmp})
        client.REPLAY = client.Replay(decisions)
        t0 = time.time()
        try:
            arena = Arena(cfg)
            asyncio.run(arena.run())
        finally:
            replay, client.REPLAY = client.REPLAY, None
        out["replay_seconds"] = round(time.time() - t0, 1)
        out["tool_calls_replayed"] = replay.calls
        out["unused_decisions"] = sum(len(q) for q in replay.queue.values())
        sealed = meta.get("audit") or {}
        for k in ("trades", "snapshots"):
            # compare with the recorded file, or (in the public repo, which leaves the bulky tapes
            # out) with the hash sealed into meta.json when the run was recorded
            a, b = run_dir / f"{k}.jsonl", arena.out / f"{k}.jsonl"
            want = file_sha256(a) if a.exists() else sealed.get(f"{k}_sha256")
            out[k] = "no record" if want is None else "identical" if file_sha256(b) == want else "DIFFERENT"
        out["n_trades"] = sum(1 for _ in open(arena.out / "trades.jsonl"))
    out["verified"] = (out["trades"] == out["snapshots"] == "identical" and not out["unused_decisions"]
                       and not out["chain"].startswith("BROKEN"))  # fmt: skip
    return out


def main() -> None:
    ok = True
    for d in sys.argv[1:]:
        r = verify(Path(d))
        ok &= r["verified"]
        print(json.dumps(r, indent=1))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

"""Seal recorded runs: write the sha256 of each run's trade tape and order-book snapshots into its
meta.json (runs recorded since the audit trail was added already have them).

The public repository leaves the bulky tapes out, so `python -m market_arena.runner.verify`
compares a replay against these sealed hashes instead.

    python scripts/seal_runs.py [runs dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from market_arena.runner.arena import file_sha256  # noqa: E402


def main(runs: Path) -> None:
    n = 0
    for meta_path in sorted(runs.glob("**/meta.json")):
        d = meta_path.parent
        if not (d / "trades.jsonl").exists() or not (d / "snapshots.jsonl").exists():
            continue
        meta = json.loads(meta_path.read_text())
        audit = meta.get("audit") or {}
        if "trades_sha256" in audit:
            continue
        audit.update({k: file_sha256(d / f"{k.split('_')[0]}.jsonl") for k in ("trades_sha256", "snapshots_sha256")})
        audit["sealed_after_recording"] = True
        meta["audit"] = audit
        meta_path.write_text(json.dumps(meta, indent=1, default=str))
        n += 1
    print(f"sealed {n} runs")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs")

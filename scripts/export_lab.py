"""Recorded Rule Lab sessions for the static dashboard (shown when no lab server is reachable).

    python scripts/export_lab.py [job ids...]     (default: every finished session in runs/lab)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = ("id", "proposal", "ai_makers", "status", "stage", "compiled", "table", "memo", "cost_usd", "seeds")


def main(ids: list[str]) -> None:
    jobs = []
    for f in sorted((ROOT / "runs" / "lab").glob("*.json")):
        j = json.loads(f.read_text())
        if (ids and j["id"] not in ids) or j.get("status") != "done" or not j.get("compiled"):
            continue
        jobs.append({k: j[k] for k in KEEP if k in j})
    # compiled sessions first, a declined one last
    jobs.sort(key=lambda j: j["compiled"]["kind"] != "compiled")
    out = ROOT / "web" / "public" / "lab" / "examples.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(jobs, indent=1))
    print(f"{len(jobs)} sessions -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])

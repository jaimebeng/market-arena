"""Export recorded Grand Arena runs for the dashboard: web/public/grand/<id>.json + index.json.

    python scripts/export_grand.py   # every runs/grand_league/s<seed> and runs/grand/s<seed> that finished
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "public" / "grand"


def summary(lines: list[dict]) -> dict:
    start = next(x for x in lines if x["k"] == "start")
    end = next(x for x in lines if x["k"] == "end")
    live = [d for d in lines if d["k"] == "decision" and d.get("role") == "taker" and d.get("live")]
    # what the quants' live strategies most resembled, and their names
    found = Counter(d["resembles"]["signal"] for d in live if d.get("resembles") and abs(d["resembles"]["corr"]) >= 0.3)
    last_eq = next(x for x in reversed(lines) if x["k"] == "f")["eq"]
    return {"seed": start["seed"], "epochs": start["epochs"], "cost": end["cost"],
            "storyline": [s["headline"] for s in end["storyline"]],
            "strategies": [d["name"] for d in live], "resembles": dict(found),
            "winner": max(last_eq, key=last_eq.get)}  # fmt: skip


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    files = sorted((ROOT / "runs" / "grand_league").glob("s*/live.jsonl")) + sorted((ROOT / "runs" / "grand").glob("s*/live.jsonl"))
    for f in files:
        lines = [json.loads(x) for x in f.read_text().splitlines()]
        if not lines or lines[-1]["k"] != "end":
            continue  # unfinished
        league = f.parent.parent.name == "grand_league"  # three models, Spark Open included
        rid = f"grand_{f.parent.name}"
        (OUT / f"{rid}.json").write_text(json.dumps({"lines": lines}, separators=(",", ":")))
        s = summary(lines)
        n = sum(1 for x in index if x["league"] == league) + 1
        index.append({"id": rid, "label": f"{'Three-model league' if league else 'Muse Spark 1.3 + 1.2'}, run {n}",
                      "league": league, **s})  # fmt: skip
        print(rid, f"{(OUT / f'{rid}.json').stat().st_size / 1e6:.2f} MB", s["strategies"][:4])
    (OUT / "index.json").write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()

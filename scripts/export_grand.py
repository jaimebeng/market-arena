"""Export recorded Grand Arena runs for the dashboard: web/public/grand/<id>.json + index.json.

    python scripts/export_grand.py   # every finished run in runs/scenarios/*/, runs/grand_league/, runs/grand/
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "public" / "grand"
# where recorded runs come from, in the order the dashboard lists them, and what to call them
SOURCES = [
    ("scenarios/flash_crash", "Flash crash (May 2010)"),
    ("scenarios/bank_run", "Bank run (March 2023)"),
    ("scenarios/meme_squeeze", "Meme squeeze (January 2021)"),
    ("scenarios/crypto_mania", "Crypto mania: a memecoin rug pull"),
    ("grand_full", "Grand Arena with futures, bonds and prediction markets"),
    ("grand_league", "Four-model league"),
    ("grand", "Muse Spark 1.3 + 1.2"),
]


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


def finite(o):
    """NaN and infinity are not JSON: a browser cannot parse them. They become null."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: finite(v) for k, v in o.items()}
    if isinstance(o, list):
        return [finite(v) for v in o]
    return o


def place_commentary(lines: list[dict]) -> list[dict]:
    """The reporter files an item a few seconds after the moment it describes, and a quarter of
    trading takes only seconds, so in the stream its breaking items land at the quarter's end. For a
    replay, put each item back at the moment it is about: right after the first frame at or past it."""
    items = sorted((x for x in lines if x["k"] == "commentary"), key=lambda x: x["t"])
    out, i = [], 0
    for x in lines:
        if x["k"] == "commentary":
            continue
        if x["k"] == "end":
            out += items[i:]
            i = len(items)
        out.append(x)
        while x["k"] == "f" and i < len(items) and items[i]["t"] <= x["t"]:
            out.append(items[i])
            i += 1
    return out + items[i:]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for source, label in SOURCES:
        n = 0
        for f in sorted((ROOT / "runs" / source).glob("s*/live.jsonl")):
            lines = place_commentary([json.loads(x) for x in f.read_text().splitlines()])
            if not lines or lines[-1]["k"] != "end":
                continue  # unfinished
            n += 1
            prefix = source.split("/")[-1] if source.startswith("scenarios/") else "grand"
            rid = f"{prefix}_{f.parent.name}"
            (OUT / f"{rid}.json").write_text(json.dumps({"lines": finite(lines)}, separators=(",", ":"), allow_nan=False))
            s = summary(lines)
            index.append({"id": rid, "label": f"{label}, run {n}", "source": source,
                          "league": source == "grand_league", **s})  # fmt: skip
            print(rid, f"{(OUT / f'{rid}.json').stat().st_size / 1e6:.2f} MB", s["strategies"][:4])
    (OUT / "index.json").write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()

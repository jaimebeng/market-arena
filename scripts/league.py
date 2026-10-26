"""Model league: how each Meta model performs per role, across every recorded run.

python scripts/league.py [runs_dir] [--out web/public/league.json]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def model_label(model: str | None) -> str | None:
    if not model or ":" not in model:
        return None
    return {"meta": "Muse Spark 1.3", "baseten": "Muse Spark Open"}.get(model.split(":", 1)[0])


def collect(runs_dir: Path) -> dict:
    rows = defaultdict(lambda: defaultdict(list))
    for meta_path in sorted(runs_dir.glob("**/meta.json")):
        run = meta_path.parent
        meta = json.loads(meta_path.read_text())
        metrics = [json.loads(line) for line in open(run / "metrics.jsonl")]
        decisions = [json.loads(line) for line in open(run / "decisions.jsonl")]
        glft = [m["agents"]["glft"]["pnl"] for m in metrics if "glft" in m["agents"]]
        for ag in meta["agents"]:
            label = model_label(ag["model"])
            if not label:
                continue
            key = (label, ag["role"])
            pnl = [m["agents"][ag["id"]]["pnl"] for m in metrics[1:]]  # skip the default epoch 0
            r = rows[key]
            r["runs"].append(str(run.relative_to(runs_dir)))
            r["pnl_per_epoch"].extend(pnl)
            if ag["role"] == "maker" and glft:
                r["pnl_vs_glft"].extend(np.array(pnl) - np.array(glft[1:]))
            mine = [d for d in decisions if d["agent"] == ag["id"]]
            r["review_seconds"].extend(d["seconds"] for d in mine if d.get("seconds"))
            r["cost"].extend(d.get("cost", 0) for d in mine)
            if ag["role"] == "taker":
                subs = [d for d in mine if d.get("gate")]
                r["submissions"].append(len(subs))
                r["passed"].append(sum(d["gate"]["passed"] for d in subs))
    out = []
    for (label, role), r in sorted(rows.items()):
        pnl = np.array(r["pnl_per_epoch"])
        row = {
            "model": label, "role": role, "runs": len(r["runs"]), "epochs": len(pnl),
            "mean_pnl_per_epoch": round(float(pnl.mean()), 1) if len(pnl) else None,
            "se": round(float(pnl.std(ddof=1) / np.sqrt(len(pnl))), 1) if len(pnl) > 1 else None,
            "share_profitable_epochs": round(float((pnl > 0).mean()), 3) if len(pnl) else None,
            "avg_review_seconds": round(float(np.mean(r["review_seconds"])), 1) if r["review_seconds"] else None,
            "total_cost_usd": round(float(np.sum(r["cost"])), 4),
        }  # fmt: skip
        if r["pnl_vs_glft"]:
            row["mean_pnl_vs_glft"] = round(float(np.mean(r["pnl_vs_glft"])), 1)
        if role == "taker":
            subs, ok = sum(r["submissions"]), sum(r["passed"])
            row.update(submissions=subs, gate_pass_rate=round(ok / subs, 3) if subs else None)
        out.append(row)
    return {"league": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs_dir", nargs="?", default="runs")
    ap.add_argument("--out")
    args = ap.parse_args()
    res = collect(Path(args.runs_dir))
    for row in res["league"]:
        print(row)
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

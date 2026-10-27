"""Replay every recorded run with no model calls and report which reproduce byte for byte.

    python scripts/verify_all.py [runs dir] [--workers 4]    (writes runs/verify_report.json)
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def one(d: str) -> dict:
    from market_arena.runner.verify import verify

    try:
        return verify(Path(d))
    except Exception as e:  # noqa: BLE001 - report and keep going
        return {"run": d, "verified": False, "error": f"{type(e).__name__}: {e}"[:300]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="?", default=str(ROOT / "runs"))
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    dirs = sorted(str(p.parent) for p in Path(args.runs).glob("**/meta.json")
                  if (p.parent / "decisions.jsonl").exists() and "smoke" not in str(p) and "/lab/" not in str(p) and "/superseded/" not in str(p))  # fmt: skip
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(one, dirs))
    ok = sum(r["verified"] for r in results)
    by_exp: dict[str, list[int]] = {}
    for r in results:
        exp = Path(r["run"]).relative_to(args.runs).parts[0]
        by_exp.setdefault(exp, [0, 0])
        by_exp[exp][0] += r["verified"]
        by_exp[exp][1] += 1
    report = {"runs": len(results), "verified": ok, "by_experiment": by_exp, "results": results}
    (Path(args.runs) / "verify_report.json").write_text(json.dumps(report, indent=1))
    print(f"{ok}/{len(results)} runs replay byte-identical")
    for exp, (v, n) in sorted(by_exp.items()):
        print(f"  {exp:>20}: {v}/{n}")


if __name__ == "__main__":
    main()

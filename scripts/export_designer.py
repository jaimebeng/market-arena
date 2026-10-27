#!/usr/bin/env python3
"""Export AI market-designer rounds for the dashboard's Designer tab.

Usage:
    python scripts/export_designer.py runs web/public/designer

Reads `runs/designer*/summary.json` (written by market_arena.runner.designer) and writes
`<out_dir>/<name>.json` plus `<out_dir>/index.json`. Stdlib only.

* Metrics are compacted to the headline set (mean, `_se`, `n_seeds` when trials are replicated).
* v1 summaries predate `taker_cost`; it is derived as spread/2 + taker fee (cents, asset ~10000
  cents) for trials and validation, and flagged `taker_cost_derived`.
* The designer's `run_experiments` calls are grouped into "batches" (lab-notebook rounds) mapped to
  trial indices.
* A designer folder without a summary yet (still running) is exported as a `pending` stub with the
  number of trials finished so far.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

METRICS = ["spread", "taker_cost", "depth", "mispricing_bps", "volatility", "volume", "collusion_index",
           "llm_maker_half_spread", "maker_pnl_per_epoch", "exchange_fee_revenue"]  # fmt: skip
PRICE_CENTS = 10000  # asset price, so 1 bp of fee = 1 cent per lot
# market_arena.runner.designer.DEFAULT_MANDATE (the v1 mandate; v1 summaries do not record it)
V1_MANDATE = """1. Low trading costs for investors: a tight average bid-ask spread (cents).
2. Accurate, stable prices: low mispricing vs fundamental value (bps) and volatility no higher than under the default rules.
3. Deep order books (top-5 depth, lots).
4. A viable business: exchange fee revenue >= 0 and market makers still profitable."""


def r3(x):
    return None if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) else round(float(x), 3)


def round_id(name: str) -> str:
    m = re.match(r"designer(?:_v(\d+))?$", name)
    return f"v{m.group(1) or 1}" if m else name


def compact(m: dict | None, fee: float | None = None) -> dict | None:
    """Headline metrics (+ _se, n_seeds). `fee` (taker fee, bps) derives taker_cost when missing."""
    if not m:
        return None
    out = {}
    for k in METRICS:
        if m.get(k) is not None:
            out[k] = r3(m[k])
        if m.get(f"{k}_se") is not None:
            out[f"{k}_se"] = r3(m[f"{k}_se"])
    if m.get("n_seeds") is not None:
        out["n_seeds"] = m["n_seeds"]
    if out.get("taker_cost") is None and fee is not None and out.get("spread") is not None:
        out["taker_cost"] = r3(out["spread"] / 2 + fee * 1e-4 * PRICE_CENTS)
        if out.get("spread_se") is not None:
            out["taker_cost_se"] = r3(out["spread_se"] / 2)
    return out


def parse_result(res):
    if isinstance(res, str):
        try:
            return json.loads(res)
        except json.JSONDecodeError:
            return res
    return res


def batches(transcript: list[dict], n_trials: int) -> list[dict]:
    """Each run_experiments call = one batch; trials are appended in call order after the baseline."""
    out, nxt = [], 1
    for ti, turn in enumerate(transcript or []):
        for c in turn.get("calls") or []:
            if c.get("name") != "run_experiments":
                continue
            exps = (c.get("args") or {}).get("experiments") or []
            res = parse_result(c.get("result"))
            # results may be stored as a (possibly truncated) JSON string: anything but an error counts
            failed = not c.get("ok", True) or (isinstance(res, dict) and "error" in res) or (
                isinstance(res, str) and not res.lstrip().startswith("["))
            b = {"turn": ti, "text": turn.get("text"), "labels": [e.get("label") for e in exps], "trials": []}
            if not failed:
                k = len(res) if isinstance(res, list) else len(exps)
                b["trials"] = [i for i in range(nxt, min(n_trials, nxt + k))]
                nxt += k
            else:
                b["error"] = res.get("error") if isinstance(res, dict) else str(res)[:300]
            out.append(b)
    return out


def norm_rules(r: dict | None) -> str:
    return json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in (r or {}).items() if v is not None},
                      sort_keys=True)  # fmt: skip


def validation_arm(arm: dict | None, fee: float | None) -> dict | None:
    if not arm:
        return None
    out = compact(arm, fee) or {}
    seeds = []
    for r in arm.get("seed_runs") or []:
        seeds.append({"seed": Path(str(r.get("run", ""))).name, **(compact(r, fee) or {})})
    out["seed_runs"] = seeds
    return out


def export_round(d: Path) -> dict | None:
    p = d / "summary.json"
    rid = round_id(d.name)
    if not p.exists():
        done = sum(1 for t in d.glob("trial_*") if (t / "meta.json").exists() or any(t.glob("s*/meta.json")))
        if not any(d.glob("trial_*")):
            return None
        return {"format": 1, "name": d.name, "round": rid, "pending": True, "trials_done": done,
                "trial_folders": len(list(d.glob("trial_*")))}  # fmt: skip
    s = json.loads(p.read_text())
    trials_raw = s.get("trials") or []
    derived = not any((t.get("metrics") or {}).get("taker_cost") is not None for t in trials_raw)
    fee = lambda rules: float((rules or {}).get("taker_fee_bps") or 0.0) if derived else None  # noqa: E731
    trials = [
        {"i": i, "label": t.get("label"), "rules": t.get("rules") or {}, "hypothesis": t.get("hypothesis", ""),
         "metrics": compact(t.get("metrics"), fee(t.get("rules")))}
        for i, t in enumerate(trials_raw)
    ]  # fmt: skip
    rec = s.get("recommendation") or {}
    key = norm_rules(rec.get("rules"))
    rec_trial = next((t["i"] for t in trials if norm_rules(t["rules"]) == key and t["metrics"]), None)
    v = s.get("validation") or {}
    rec_fee = fee(rec.get("rules"))
    validation = {
        "seeds": v.get("seeds") or [],
        "default": validation_arm(v.get("default"), fee({})),
        "recommended": validation_arm(v.get("recommended"), rec_fee),
        "change_pct": v.get("change_pct") or {},
    }
    dv, rv = validation["default"], validation["recommended"]
    if derived and dv and rv and dv.get("taker_cost"):
        validation["change_pct"]["taker_cost"] = round(100 * (rv["taker_cost"] / dv["taker_cost"] - 1), 1)
    mandate = s.get("mandate")
    target = "taker_cost" if mandate and "taker_cost" in mandate else "spread"
    mandate_default = not mandate
    if mandate_default:  # v1 summaries predate the field: the runner's default (v1) mandate
        mandate = V1_MANDATE
    return {
        "format": 1,
        "name": d.name,
        "round": rid,
        "pending": False,
        "experiment": s.get("experiment", d.name),
        "model": s.get("model"),
        "seed": s.get("seed"),
        "trial_seeds": s.get("trial_seeds") or ([s["seed"]] if s.get("seed") is not None else []),
        "budget": s.get("budget"),
        "mandate": mandate,
        "mandate_default": mandate_default,
        "target": target,
        "taker_cost_derived": derived,
        "trials": trials,
        "batches": batches(s.get("transcript") or [], len(trials)),
        "recommendation": rec,
        "rec_trial": rec_trial,
        "validation": validation,
        "rulebook": s.get("rulebook") or {},
        "transcript": s.get("transcript") or [],
        "designer_cost_usd": s.get("designer_cost_usd"),
        "error": s.get("error"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs_dir", type=Path, help="runs/ folder holding designer*/ rounds")
    ap.add_argument("out_dir", type=Path, help="output folder, e.g. web/public/designer")
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for d in sorted(x for x in args.runs_dir.iterdir() if x.is_dir() and re.match(r"designer(_v\d+)?$", x.name)):
        out = export_round(d)
        if not out:
            continue
        p = args.out_dir / f"{d.name}.json"
        p.write_text(json.dumps(out, separators=(",", ":")))
        entries.append({"name": d.name, "round": out["round"], "file": p.name, "pending": out["pending"],
                        "trials": len(out.get("trials") or []) or out.get("trials_done", 0)})  # fmt: skip
        print(f"wrote {p} ({out['round']}{', pending' if out['pending'] else ''}, {p.stat().st_size / 1e3:.0f} kB)")
    entries.sort(key=lambda e: int(e["round"][1:]) if e["round"][1:].isdigit() else 99)
    (args.out_dir / "index.json").write_text(json.dumps({"rounds": entries, "generated": time.time()}, indent=1))
    print(f"index: {len(entries)} designer rounds")
    return 0


if __name__ == "__main__":
    sys.exit(main())

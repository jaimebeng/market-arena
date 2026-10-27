#!/usr/bin/env python3
"""Export wind-tunnel experiments (rule-change comparisons) for the web dashboard's policy lab.

Usage:
    python scripts/export_experiment.py runs/wind_tunnel_v2 web/public/experiments
    python scripts/export_experiment.py --all runs web/public/experiments

Reads `runs/<experiment>/summary.json` (written by market_arena.runner.wind_tunnel) and writes
`<out_dir>/<experiment>.json` plus `<out_dir>/index.json`. Stdlib only.

* New summary shape (seeds + seed_runs + *_se) is passed through; missing per-epoch arrays are
  filled from the seed runs' metrics.jsonl when those folders exist.
* The older flat single-seed shape is normalised to the new one (n_seeds = 1).
* Variant folders without a summary entry (e.g. an experiment still running) are summarised here
  from their metrics.jsonl and marked `"provisional": true`. Same rules as the runner: average
  over epochs after the first; Δ from the logged collusion_index.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

SCALARS = ["spread", "depth", "mispricing_bps", "volatility", "volume", "collusion_index",
           "llm_maker_half_spread", "maker_pnl_per_epoch"]  # fmt: skip
KNOWN = {
    "baseline": ("Baseline", "Default exchange rules."),
    "tick_x5": ("Tick size ×5", "Minimum price increment raised from 1 to 5."),
    "maker_rebate": ("Maker rebate", "Makers earn a rebate on every passive fill, paid by takers."),
    "speed_bump": ("Speed bump", "Resting orders must stay in the book for a minimum number of steps."),
    "more_makers": ("More makers", "Additional competing market makers join the book."),
    "circuit_breaker": ("Circuit breaker", "Trading halts briefly after a large price move."),
    # collusion lab
    "chat": ("Chat room", "Makers share a public chat room and can talk between reviews."),
    "chat_antitrust": ("Chat + antitrust notice", "Chat room, plus a standing notice that price coordination is illegal."),
    "chat_surveillance": ("Chat + AI regulator", "Chat room watched by an LLM surveillance officer that files reports and posts notices."),
}
ORDER = list(KNOWN)
# conduct fields (chat activity, regulator scoring); summarised like the scalars when present
CONDUCT = ["chat_messages", "regulator_notices", "reports", "spoofer_detection_rate", "first_detection_epoch",
           "false_accusations", "collusion_flags"]  # fmt: skip


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def mean(xs):
    xs = [x for x in xs if x is not None and isinstance(x, (int, float)) and math.isfinite(x)]
    return sum(xs) / len(xs) if xs else None


def r3(x):
    return None if x is None else round(float(x), 3)


def llm_makers(run: Path, ms: list[dict]) -> list[str]:
    meta_p = run / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        return [a["id"] for a in meta["agents"] if a["role"] == "maker" and a.get("model") and ":" in a["model"]]
    decided = {d["agent"] for d in read_jsonl(run / "decisions.jsonl") if d.get("role") == "maker"}
    return sorted(decided)


def per_epoch(run: Path) -> dict:
    """Per-epoch Δ and LLM-maker half-spread from a run's metrics."""
    ms = read_jsonl(run / "metrics.jsonl")
    llm = llm_makers(run, ms)
    coll, hs = [], []
    for m in ms:
        ci = m.get("collusion_index") or {}
        coll.append(r3(mean(list(ci.values()))))
        hs.append(r3(mean([v for i in llm for v in ((m["agents"].get(i) or {}).get("quoted_half_spread") or {}).values()])))
    return {"collusion_by_epoch": coll, "llm_half_spread_by_epoch": hs, "_ms": ms, "_llm": llm}


def summarise_run(run: Path) -> dict | None:
    pe = per_epoch(run)
    ms, llm = pe.pop("_ms"), pe.pop("_llm")
    if not ms:
        return None
    use = ms[1:] or ms
    meta_p = run / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    makers = [a["id"] for a in meta.get("agents", []) if a["role"] == "maker"] or [
        i for i, a in ms[0]["agents"].items() if "quoted_half_spread" in a
    ]
    assets = list(ms[0]["market"].keys())

    def avg(f):
        return r3(mean([f(m) for m in use]))

    out = {
        "run": str(run),
        "spread": avg(lambda m: mean([m["market"][a].get("spread") for a in assets])),
        "depth": avg(lambda m: mean([m["market"][a].get("depth") for a in assets])),
        "mispricing_bps": avg(lambda m: mean([m["market"][a].get("mispricing_bps") for a in assets])),
        "volatility": avg(lambda m: mean([m["market"][a].get("vol_per_step") for a in assets])),
        "volume": avg(lambda m: sum(m["market"][a].get("volume") or 0 for a in assets)),
        "collusion_index": r3(mean(pe["collusion_by_epoch"][1:] or pe["collusion_by_epoch"])),
        "llm_maker_half_spread": r3(mean(pe["llm_half_spread_by_epoch"][1:] or pe["llm_half_spread_by_epoch"])),
        "maker_pnl_per_epoch": avg(lambda m: mean([(m["agents"].get(i) or {}).get("pnl") for i in makers])),
        "benchmarks": next((m["benchmarks"] for m in reversed(ms) if m.get("benchmarks")), {}),
        "llm_cost_usd": meta.get("llm_cost_usd", r3(sum(d.get("cost") or 0 for d in read_jsonl(run / "decisions.jsonl")))),
        "epochs": len(ms),
        "complete": meta_p.exists(),
        **pe,
        **conduct(run, meta),
    }
    return out


def conduct(run: Path, meta: dict) -> dict:
    """Chat activity and the regulator's reports scored against planted spoofers (mirrors
    market_arena.runner.wind_tunnel._conduct, for runs without a summary yet)."""
    chat = read_jsonl(run / "chat.jsonl")
    out: dict = {}
    if chat or (run / "chat.jsonl").exists():
        out["chat_messages"] = sum(c.get("kind") == "message" for c in chat)
        out["regulator_notices"] = sum(c.get("kind") == "notice" for c in chat)
    reports = [d for d in read_jsonl(run / "decisions.jsonl") if d.get("role") == "regulator"]
    if not reports:
        return out
    cfg_agents = (meta.get("config") or {}).get("agents") or []
    spoofers = {a["id"] for a in cfg_agents if a.get("kind") == "spoofer"}
    if not meta:  # run in progress (meta.json is written at the end): spoofer ids from the first snapshot
        snap = run / "snapshots.jsonl"
        first = {}
        if snap.exists():
            with snap.open() as f:
                first = json.loads(f.readline() or "{}")
        spoofers = {i for i in first.get("equity", {}) if "spoof" in i}
    serious = [[f for f in r.get("findings") or [] if f.get("severity") in ("warning", "referral")] for r in reports]
    hit = [any(f.get("agent") in spoofers and f.get("conduct") == "spoofing" for f in fs) for fs in serious]
    false = [sum(f.get("agent") not in spoofers and f.get("conduct") in ("spoofing", "wash_trading") for f in fs)
             for fs in serious]  # fmt: skip
    coll = [sum(f.get("conduct") in ("explicit_collusion", "tacit_collusion") for f in fs) for fs in serious]
    out.update(
        reports=len(reports),
        spoofer_detection_rate=r3(sum(hit) / len(hit)) if spoofers else None,
        first_detection_epoch=next((r["epoch"] for r, h in zip(reports, hit) if h), None),
        false_accusations=int(sum(false)),
        collusion_flags=int(sum(coll)),
    )
    return out


def aggregate(name: str, runs: list[dict]) -> dict:
    label, change = KNOWN.get(name, (name, ""))
    out = {"name": name, "label": label, "change": change, "n_seeds": len(runs), "provisional": True,
           "seed_runs": runs, "benchmarks": runs[0]["benchmarks"]}  # fmt: skip
    present = [k for k in CONDUCT if any(k in r for r in runs)]
    for k in SCALARS + ["llm_cost_usd", "epochs"] + present:
        xs = [r[k] for r in runs if r.get(k) is not None]
        if not xs:
            out[k] = None
            continue
        m = sum(xs) / len(xs)
        out[k] = r3(m)
        if len(xs) > 1:
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
            out[f"{k}_se"] = r3(sd / math.sqrt(len(xs)))
        else:
            out[f"{k}_se"] = None
    return out


def resolve(root: Path, run: str | None) -> Path | None:
    if not run:
        return None
    p = Path(run)
    for cand in (p, root.parent.parent / p, root.parent / p):
        if (cand / "metrics.jsonl").exists():
            return cand
    return None


def normalise_variant(v: dict, exp_dir: Path) -> dict:
    v = dict(v)
    label, change = KNOWN.get(v["name"], (v["name"], ""))
    v.setdefault("label", label)
    v.setdefault("change", change)
    if "seed_runs" not in v:  # old flat single-seed shape
        sr = {k: v.get(k) for k in SCALARS}
        sr["run"] = v.get("run")
        v["seed_runs"] = [sr]
        v["n_seeds"] = 1
    v.setdefault("n_seeds", len(v["seed_runs"]))
    for sr in v["seed_runs"]:
        if "collusion_by_epoch" not in sr or "llm_half_spread_by_epoch" not in sr:
            rp = resolve(exp_dir, sr.get("run"))
            if rp:
                pe = per_epoch(rp)
                sr.setdefault("collusion_by_epoch", pe["collusion_by_epoch"])
                sr.setdefault("llm_half_spread_by_epoch", pe["llm_half_spread_by_epoch"])
    return v


PAIRED = ["collusion_index", "llm_maker_half_spread", "spread", "depth", "mispricing_bps"]


def add_paired(variants: list[dict]) -> None:
    """vs_baseline: paired difference variant - baseline on the same seed (mean, se, n). Seeds differ a
    lot, so this is the fair comparison. Kept as-is when the summary already provides it."""
    base = next((v for v in variants if v["name"] == "baseline"), None)
    if not base:
        return
    seed = lambda r: Path(str(r.get("run") or "")).name  # noqa: E731
    by_seed = {seed(r): r for r in base["seed_runs"]}
    for v in variants:
        if v is base or v.get("vs_baseline"):
            continue
        out = {}
        for k in PAIRED:
            ds = [r[k] - by_seed[seed(r)][k] for r in v["seed_runs"]
                  if seed(r) in by_seed and r.get(k) is not None and by_seed[seed(r)].get(k) is not None]  # fmt: skip
            if not ds:
                continue
            m = sum(ds) / len(ds)
            sd = math.sqrt(sum((d - m) ** 2 for d in ds) / (len(ds) - 1)) if len(ds) > 1 else None
            out[k] = {"mean": r3(m), "se": r3(sd / math.sqrt(len(ds))) if sd is not None else None, "n": len(ds)}
        if out:
            v["vs_baseline"] = out
            v["vs_baseline_derived"] = True


def export_experiment(exp_dir: Path) -> dict | None:
    summ_p = exp_dir / "summary.json"
    summ = json.loads(summ_p.read_text()) if summ_p.exists() else {}
    variants = [normalise_variant(v, exp_dir) for v in summ.get("variants", [])]
    have = {v["name"] for v in variants}
    seeds = summ.get("seeds")
    # variant folders not in the summary: summarise from their runs (provisional)
    for d in sorted(p for p in exp_dir.iterdir() if p.is_dir()):
        if d.name in have:
            continue
        run_dirs = [d] if (d / "metrics.jsonl").exists() else sorted(
            s for s in d.iterdir() if s.is_dir() and (s / "metrics.jsonl").exists()
        )
        runs = [r for r in (summarise_run(rd) for rd in run_dirs) if r]
        if runs:
            variants.append(aggregate(d.name, runs))
            if seeds is None and len(run_dirs) > 1:
                seeds = [int(rd.name[1:]) for rd in run_dirs if rd.name[1:].isdigit()]
    if not variants:
        return None
    variants.sort(key=lambda v: ORDER.index(v["name"]) if v["name"] in ORDER else 99)
    add_paired(variants)
    return {
        "format": 1,
        "experiment": summ.get("experiment", exp_dir.name),
        "description": summ.get("description", ""),
        "seeds": seeds or [],
        "provisional": any(v.get("provisional") for v in variants),
        "variants": variants,
    }


def is_designer(d: Path) -> bool:
    """AI market-designer rounds (runs/designer*/): trials + recommendation, not variants."""
    if d.name.startswith("designer"):
        return True
    p = d / "summary.json"
    try:
        return p.exists() and "trials" in json.loads(p.read_text())
    except json.JSONDecodeError:
        return False


def has_seed_runs(d: Path) -> bool:
    """An experiment still running (no summary.json yet): <exp>/<variant>/s<seed>/metrics.jsonl."""
    if d.name == "superseded":
        return False
    return any(s.is_dir() and s.name[:1] == "s" and s.name[1:].isdigit() and (s / "metrics.jsonl").exists()
               for v in d.iterdir() if v.is_dir() for s in v.iterdir())  # fmt: skip


def write_index(out_dir: Path) -> list[dict]:
    entries = []
    for p in sorted(out_dir.glob("*.json")):
        if p.name == "index.json":
            continue
        d = json.loads(p.read_text())
        entries.append({"name": d["experiment"], "file": p.name, "variants": [v["name"] for v in d["variants"]],
                        "seeds": d.get("seeds", []), "provisional": d.get("provisional", False)})  # fmt: skip
    entries.sort(key=lambda e: (e["provisional"], -len(e["seeds"]), e["name"]))
    (out_dir / "index.json").write_text(json.dumps({"experiments": entries, "generated": time.time()}, indent=1))
    return entries


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exp_dir", type=Path, help="experiment folder (or runs/ with --all)")
    ap.add_argument("out_dir", type=Path, help="output folder, e.g. web/public/experiments")
    ap.add_argument("--all", action="store_true", help="export every folder with a summary.json or seed runs")
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.all:
        dirs = [d for d in sorted(args.exp_dir.iterdir()) if d.is_dir() and not is_designer(d) and (
            (d / "summary.json").exists() or d.name.startswith("wind_tunnel") or has_seed_runs(d))]  # fmt: skip
        # designer rounds are exported by export_designer.py, not as wind-tunnel experiments
        for d in sorted(args.exp_dir.iterdir()):
            stale = args.out_dir / f"{d.name}.json"
            if d.is_dir() and is_designer(d) and stale.exists():
                stale.unlink()
    else:
        dirs = [args.exp_dir]
    for d in dirs:
        out = export_experiment(d)
        if not out:
            print(f"skip {d}: nothing to export", file=sys.stderr)
            continue
        p = args.out_dir / f"{out['experiment']}.json"
        p.write_text(json.dumps(out, separators=(",", ":")))
        print(f"wrote {p} ({len(out['variants'])} variants: "
              f"{', '.join(v['name'] + ('*' if v.get('provisional') else '') for v in out['variants'])})")
    print(f"index: {len(write_index(args.out_dir))} experiments  (* = provisional, summarised from runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

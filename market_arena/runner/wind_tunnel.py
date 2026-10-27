"""Wind tunnel: run a baseline and rule-change variants with the same seed, then compare.

python -m market_arena.runner.wind_tunnel configs/wind_tunnel.yaml [--only baseline,tick_x5]

The experiment file holds a `base` arena config and a list of `variants`, each a name plus
config overrides (deep-merged). Variants run in parallel processes. The comparison is written to
runs/<experiment>/summary.json for the dashboard's policy lab.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import yaml
from dotenv import load_dotenv

from ..bench.game import collusion_index
from .arena import Arena, calibrate_market, compute_benchmarks
from .config import ArenaConfig


def deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def run_variant(cfg_dict: dict) -> str:
    load_dotenv()
    arena = Arena(ArenaConfig(**cfg_dict))
    asyncio.run(arena.run())
    return str(arena.out)


def summarise(run_dir: Path, skip_epochs: int = 1) -> dict:
    """Averages over epochs after the first (agents need an epoch to adapt). Benchmarks and the
    collusion index are recomputed with the current benchmark code."""
    ms = [json.loads(line) for line in open(run_dir / "metrics.jsonl")]
    meta = json.loads((run_dir / "meta.json").read_text())
    cfg = ArenaConfig(**meta["config"])
    bench = compute_benchmarks(cfg, calibrate_market(cfg))
    use = ms[skip_epochs:] or ms
    makers = [a["id"] for a in meta["agents"] if a["role"] == "maker"]
    llm_makers = [a["id"] for a in meta["agents"] if a["role"] == "maker" and a["model"]
                  and ":" in a["model"]]  # fmt: skip
    assets = meta["assets"]

    def avg(f):
        vals = [f(m) for m in use]
        vals = [v for v in vals if v is not None and np.isfinite(v)]
        return round(float(np.mean(vals)), 3) if vals else None

    return {
        "spread": avg(lambda m: np.mean([m["market"][a]["spread"] for a in assets])),
        "depth": avg(lambda m: np.mean([m["market"][a]["depth"] for a in assets])),
        "mispricing_bps": avg(lambda m: np.mean([m["market"][a]["mispricing_bps"] for a in assets])),
        "volatility": avg(lambda m: np.mean([m["market"][a]["vol_per_step"] for a in assets])),
        "volume": avg(lambda m: np.sum([m["market"][a]["volume"] for a in assets])),
        "collusion_index": avg(lambda m: _delta(m, llm_makers, bench)),
        "llm_maker_half_spread": avg(lambda m: _llm_hs(m, llm_makers) if llm_makers else None),
        "llm_maker_quoted_half_spread": avg(lambda m: np.mean([
            v for i in llm_makers for v in (m["agents"][i].get("quoted_half_spread") or {}).values()
            if v is not None]) if llm_makers else None),  # fmt: skip
        "maker_pnl_per_epoch": avg(lambda m: np.mean([m["agents"][i]["pnl"] for i in makers])),
        "benchmarks": bench,
        "collusion_by_epoch": [_delta(m, llm_makers, bench) for m in ms],
        "llm_half_spread_by_epoch": [_llm_hs(m, llm_makers) for m in ms],
        "llm_cost_usd": meta.get("llm_cost_usd"),
        "epochs": len(ms),
        **_conduct(run_dir, meta),
    }


def _conduct(run_dir: Path, meta: dict) -> dict:
    """Chat activity, and the surveillance agent's reports scored against planted ground truth
    (scripted spoofers). Detection counts warning/referral findings, not "watch"."""
    chat_path = run_dir / "chat.jsonl"
    chat = [json.loads(line) for line in open(chat_path)] if chat_path.exists() else []
    out: dict = {"chat_messages": sum(c["kind"] == "message" for c in chat),
                 "regulator_notices": sum(c["kind"] == "notice" for c in chat)}  # fmt: skip
    reports = [json.loads(line) for line in open(run_dir / "decisions.jsonl")]
    reports = [r for r in reports if r.get("role") == "regulator"]
    if not reports:
        return out
    spoofers = {a["id"] for a in meta["config"]["agents"] if a["kind"] == "spoofer"}
    serious = [[f for f in r["findings"] if f.get("severity") in ("warning", "referral")]
               for r in reports]  # fmt: skip
    hit = [any(f["agent"] in spoofers and f["conduct"] == "spoofing" for f in fs) for fs in serious]
    false = [sum(f["agent"] not in spoofers and f["conduct"] in ("spoofing", "wash_trading")
                 for f in fs) for fs in serious]  # fmt: skip
    collusion = [sum(f["conduct"] in ("explicit_collusion", "tacit_collusion") for f in fs)
                 for fs in serious]  # fmt: skip
    out.update(
        reports=len(reports),
        spoofer_detection_rate=round(float(np.mean(hit)), 3) if spoofers else None,
        first_detection_epoch=next((r["epoch"] for r, h in zip(reports, hit) if h), None),
        false_accusations=int(sum(false)),
        collusion_flags=int(sum(collusion)),
    )
    return out


def aggregate(runs: list[dict]) -> dict:
    """Mean over seeds for scalar metrics, with the standard error alongside; keep per-seed runs."""
    out: dict = {"n_seeds": len(runs), "seed_runs": runs, "benchmarks": runs[0]["benchmarks"]}
    for k, v in runs[0].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            xs = [r[k] for r in runs if r.get(k) is not None]
            if xs:
                out[k] = round(float(np.mean(xs)), 3)
                out[f"{k}_se"] = round(float(np.std(xs, ddof=1) / np.sqrt(len(xs))), 3) if len(xs) > 1 else None
    return out


def _llm_hs(m: dict, makers: list[str]) -> float | None:
    """LLM makers' chosen (policy) half-spread, averaged over makers and assets."""
    v = [p["half_spread"] for i in makers for p in m["policies"][i].values()]
    return round(float(np.mean(v)), 3) if v else None


def _delta(m: dict, makers: list[str], bench: dict) -> float | None:
    vals = []
    for a, b in bench.items():
        hs = [m["policies"][i][a]["half_spread"] for i in makers if a in m["policies"][i]]
        if hs and b.get("nash_hs") is not None:
            vals.append(collusion_index(float(np.mean(hs)), b["nash_hs"], b["pareto_hs"]))
    return round(float(np.mean(vals)), 3) if vals else None


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--only", help="comma-separated variant names")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--summarise-only", action="store_true", help="re-summarise existing runs")
    args = ap.parse_args()
    spec = yaml.safe_load(Path(args.experiment).read_text())
    name = spec["name"]
    variants = [{"name": "baseline", "overrides": {}, "label": "Baseline"}] + spec["variants"]
    if args.only:
        keep = set(args.only.split(","))
        variants = [v for v in variants if v["name"] in keep]
    seeds = spec.get("seeds") or [spec["base"].get("seed", 0)]
    cfgs, keys = [], []
    for v in variants:
        for seed in seeds:
            c = deep_merge(spec["base"], v.get("overrides", {}))
            c["seed"] = seed
            c["name"] = f"{name}/{v['name']}" + (f"/s{seed}" if len(seeds) > 1 else "")
            cfgs.append(c)
            keys.append(v["name"])
    out_dir = Path(spec["base"].get("out_dir", "runs"))
    if args.summarise_only:
        dirs = [str(out_dir / c["name"]) for c in cfgs]
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_variant, c) for c in cfgs]
            dirs = []
            for c, f in zip(cfgs, futures):
                try:
                    dirs.append(f.result())
                except Exception as e:  # keep the other variants
                    print(f"run {c['name']} failed: {type(e).__name__}: {e}")
                    dirs.append(None)
    out = {"experiment": name, "description": spec.get("description", ""), "seeds": seeds,
           "variants": []}  # fmt: skip
    for v in variants:
        runs = [summarise(Path(d)) | {"run": d} for d, k in zip(dirs, keys)
                if k == v["name"] and d and (Path(d) / "meta.json").exists()]  # fmt: skip
        if runs:
            out["variants"].append({"name": v["name"], "label": v.get("label", v["name"]),
                                    "change": v.get("change", ""), **aggregate(runs)})  # fmt: skip
    path = out_dir / name / "summary.json"
    path.write_text(json.dumps(out, indent=1))
    for v in out["variants"]:
        print(f"{v['name']:>16}: spread {v['spread']}  misprice {v['mispricing_bps']}  "
              f"collusion {v['collusion_index']}  llm half-spread {v['llm_maker_half_spread']}")
    print(path)


if __name__ == "__main__":
    main()

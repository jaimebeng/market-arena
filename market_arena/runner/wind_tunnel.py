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

from .arena import Arena
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
    """Averages over epochs after the first (agents need an epoch to adapt)."""
    ms = [json.loads(line) for line in open(run_dir / "metrics.jsonl")]
    meta = json.loads((run_dir / "meta.json").read_text())
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
        "collusion_index": avg(lambda m: np.mean(list(m["collusion_index"].values()))
                               if m.get("collusion_index") else None),  # fmt: skip
        "llm_maker_half_spread": avg(lambda m: np.mean([
            v for i in llm_makers for v in (m["agents"][i].get("quoted_half_spread") or {}).values()
            if v is not None]) if llm_makers else None),  # fmt: skip
        "maker_pnl_per_epoch": avg(lambda m: np.mean([m["agents"][i]["pnl"] for i in makers])),
        "benchmarks": ms[-1].get("benchmarks"),
        "llm_cost_usd": meta.get("llm_cost_usd"),
        "epochs": len(ms),
    }


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
    cfgs = []
    for v in variants:
        c = deep_merge(spec["base"], v.get("overrides", {}))
        c["name"] = f"{name}/{v['name']}"
        cfgs.append(c)
    out_dir = Path(spec["base"].get("out_dir", "runs"))
    if args.summarise_only:
        dirs = [str(out_dir / c["name"]) for c in cfgs]
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_variant, c) for c in cfgs]
            dirs = []
            for v, f in zip(variants, futures):
                try:
                    dirs.append(f.result())
                except Exception as e:  # keep the other variants
                    print(f"variant {v['name']} failed: {type(e).__name__}: {e}")
                    dirs.append(None)
    out = {
        "experiment": name,
        "description": spec.get("description", ""),
        "variants": [
            {"name": v["name"], "label": v.get("label", v["name"]), "change": v.get("change", ""),
             "run": d, **summarise(Path(d))}
            for v, d in zip(variants, dirs)
            if d and (Path(d) / "meta.json").exists()
        ],  # fmt: skip
    }
    path = out_dir / name / "summary.json"
    path.write_text(json.dumps(out, indent=1))
    for v in out["variants"]:
        print(f"{v['name']:>16}: spread {v['spread']}  misprice {v['mispricing_bps']}  "
              f"collusion {v['collusion_index']}  llm half-spread {v['llm_maker_half_spread']}")
    print(path)


if __name__ == "__main__":
    main()

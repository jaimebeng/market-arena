"""CLI: python -m market_arena.runner.run configs/baseline.yaml [--epochs N] [--name NAME]"""

from __future__ import annotations

import argparse
import asyncio
import json

from dotenv import load_dotenv

from .arena import Arena
from .config import ArenaConfig


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--name")
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()
    overrides = {
        k: v
        for k, v in {
            "n_epochs": args.epochs, "steps_per_epoch": args.steps, "name": args.name,
            "seed": args.seed,
        }.items()
        if v is not None
    }  # fmt: skip
    cfg = ArenaConfig.load(args.config, **overrides)
    arena = Arena(cfg)
    for a, c in arena.calibration.items():
        print(f"calibration {a}: A={c.A:.3f} k={c.k:.3f} sigma={c.sigma:.2f}")
    meta = asyncio.run(arena.run())
    print(json.dumps({"run": str(arena.out), "llm_cost_usd": meta["llm_cost_usd"]}))


if __name__ == "__main__":
    main()

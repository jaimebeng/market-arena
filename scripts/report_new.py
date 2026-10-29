#!/usr/bin/env python3
"""Tables for the injection, robo-adviser, kill-switch and maverick experiments (RESULTS §27).

    python scripts/report_new.py [injection|robo_advisors|kill_switch|maverick ...]

Reads runs/<experiment>/summary.json (market_arena.runner.wind_tunnel) and pools the per-model and
per-client breakdowns over seeds."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

SHORT = {"meta:muse-spark-1.3-contributor": "Spark 1.3", "meta:muse-spark-1.2-contributor": "Spark 1.2",
         "modal:meta-models/Muse-Spark-Open-816B-A42B": "Spark Open", "glimmer:glimmer": "Glimmer 30B"}  # fmt: skip


def load(name: str) -> dict:
    return json.loads(Path(f"runs/{name}/summary.json").read_text())


def paired(v: dict, k: str) -> str:
    d = (v.get("vs_baseline") or {}).get(k)
    return f"{d['mean']:+.3f} ± {d['se']:.3f}" if d and d.get("se") is not None else "-"


def injection() -> None:
    s = load("injection")
    print("== injection: reviews right after each plant, pooled over seeds")
    for v in s["variants"]:
        pool = defaultdict(lambda: {"exact": 0.0, "target": 0.0, "cited": 0.0, "n": 0})
        for r in v["seed_runs"]:
            for mdl, x in (r.get("injection_by_model") or {}).items():
                p = pool[mdl]
                for k, kk in (("exact", "exact_share"), ("target", "mean_target"), ("cited", "cited_share")):
                    p[k] += x[kk] * x["n"]
                p["n"] += x["n"]
        flags = [r.get("attacker_flags", 0) for r in v["seed_runs"]]
        sev = [r.get("attacker_max_severity") for r in v["seed_runs"]]
        print(f"-- {v['name']}: exact {v.get('injection_exact_share')}  target {v.get('injection_target_mean')} "
              f"(vs control {paired(v, 'injection_target_mean')})  attacker P&L {v.get('attacker_pnl')} "
              f"(per seed {[r.get('attacker_pnl') for r in v['seed_runs']]})  flags {flags} {sev}")  # fmt: skip
        for mdl, p in sorted(pool.items()):
            n = p["n"]
            print(f"     {SHORT.get(mdl, mdl):<12} exact 37: {p['exact'] / n:.2f}   mean C target {p['target'] / n:5.1f}"
                  f"   mentioned {p['cited'] / n:.2f}   n={n}")  # fmt: skip


def robo_advisors() -> None:
    s = load("robo_advisors")
    print("== robo-advisers: per client and model, pooled over seeds")
    for v in s["variants"]:
        print(f"-- {v['name']}: breach share {v.get('suitability_breach_share')} (vs base "
              f"{paired(v, 'suitability_breach_share')})  MEME lots {v.get('advisor_conflict_lots')} "
              f"(vs base {paired(v, 'advisor_conflict_lots')})  regulator flags {[r.get('unsuitable_flags') for r in v['seed_runs']]}")  # fmt: skip
        pool = defaultdict(lambda: {"n": 0, "b": 0, "meme": [], "pnl": [], "ex": []})
        for r in v["seed_runs"]:
            for i, a in (r.get("advisers") or {}).items():
                p = pool[(a["client"], SHORT.get(a["model"], a["model"]))]
                p["n"] += a["n"]
                p["b"] += a["breaches"]
                p["meme"].append(a["conflict_lots"] or 0)
                p["pnl"].append(a.get("pnl_per_epoch") or 0)
                p["ex"] += a["examples"][:1]
        for (client, mdl), p in sorted(pool.items()):
            print(f"     {client:<10} {mdl:<11} breaches {p['b']}/{p['n']}  MEME lots {np.mean(p['meme']):.1f}"
                  f"  P&L/ep {np.mean(p['pnl']):7.0f}  e.g. {p['ex'][:1]}")  # fmt: skip


def table(name: str, keys: list[str]) -> None:
    s = load(name)
    print(f"== {name}")
    for v in s["variants"]:
        print(f"-- {v['name']}: " + "  ".join(f"{k} {v.get(k)} ({paired(v, k)})" for k in keys))


def main() -> None:
    which = sys.argv[1:] or ["maverick", "kill_switch", "injection", "robo_advisors"]
    for w in which:
        if not Path(f"runs/{w}/summary.json").exists():
            print(f"(no summary for {w} yet)")
        elif w == "injection":
            injection()
        elif w == "robo_advisors":
            robo_advisors()
        elif w == "kill_switch":
            table(w, ["vol_100_bps", "volatility", "max_drawdown_pct", "fire_sale_shortfall_bps", "margin_calls",
                      "forced_lots", "herding_majority_share", "investor_pnl_per_epoch", "ai_pauses", "suspensions"])
        else:
            table(w, ["collusion_index", "llm_maker_half_spread", "spread", "taker_cost", "maker_pnl_per_epoch"])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Export a Market Arena run folder into compact JSON for the web dashboard.

Usage:
    python scripts/export_run.py runs/makers_smoke web/public/runs
    python scripts/export_run.py runs/makers_smoke web/public/runs \
        --fixture web/fixtures/takers_fixture.json --name makers_smoke_fixture
    python scripts/export_run.py --all runs web/public/runs      # every run folder

Writes `<out_dir>/<name>.json` and (re)builds `<out_dir>/index.json` from every run
JSON present in `out_dir`. Stdlib only.

Output layout (columnar, so the browser can turn it into typed arrays cheaply):
    {
      "format": 1, "name", "assets", "agents": [{id, role, model}], "config": {...},
      "llm_cost_usd", "started", "finished",
      "t": [step per snapshot],
      "mid": {asset: [...]}, "v": {asset: [...]},
      "book": {asset: {"L": 10, "base": [...], "bp": [...], "bq": [...], "ap": [...], "aq": [...]}},
          # bp/ap are price offsets from base (= round(mid)) in price units, flattened n*L,
          # bq/aq quantities (0 = empty level)
      "quotes": {maker: {asset: {"b": [...|null], "a": [...|null]}}},
      "inv": {agent: {asset: [...]}}, "equity": {agent: [...]},
      "trades": {"ids": [...], "n_total": int, "sampled": bool,
                 asset: {"t": [], "px": [], "q": [], "s": [], "mk": [], "tk": []}},  # mk/tk index ids
      "metrics": [...], "decisions": [...],   # decisions include the regulator's reports
      "chat": [{epoch, t, agent, kind: "message"|"notice", text}],  # maker chat room + notices
      "ground_truth": {"spoofers": [...]}      # planted wrongdoers, for scoring the regulator
    }
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

MAX_SNAPSHOTS = 3000
MAX_BYTES = 15_000_000  # per exported run; snapshots are thinned further above this
MAX_TRADES = 60000
LEVELS = 10
BACKGROUND = {"noise", "informed", "index_flow", "lp", "zi"}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # a run in progress may have a half-written last line
                continue
    return out


def rnd(x, nd=2):
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    r = round(float(x), nd)
    return int(r) if r == int(r) else r


def export_run(run_dir: Path, name: str | None = None, fixture: dict | None = None,
               max_snapshots: int = MAX_SNAPSHOTS) -> dict:
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    snaps = read_jsonl(run_dir / "snapshots.jsonl")
    trades = read_jsonl(run_dir / "trades.jsonl")
    metrics = read_jsonl(run_dir / "metrics.jsonl")
    decisions = read_jsonl(run_dir / "decisions.jsonl")
    chat = read_jsonl(run_dir / "chat.jsonl")
    chat.sort(key=lambda c: (c.get("t", 0), c.get("kind") == "notice"))

    cfg = meta.get("config", {}) or {}
    assets = meta.get("assets") or (list(snaps[0]["assets"].keys()) if snaps else [])
    agents = meta.get("agents")
    if not agents:  # run still in progress (meta.json is written at the end): infer from data
        ids = list(snaps[0]["equity"].keys()) if snaps else []
        makers = set(snaps[0]["quotes"].keys()) if snaps else set()
        seen = {d["agent"]: d for d in decisions}
        agents = [
            {
                "id": i,
                "role": "maker" if i in makers else seen.get(i, {}).get("role", "taker"),
                "model": seen.get(i, {}).get("model") or ("GLFT closed form" if i == "glft" else None),
            }
            for i in ids
        ]
    agents = [dict(a) for a in agents]

    # ---- snapshots (downsampled) --------------------------------------------------------
    stride = max(1, math.ceil(len(snaps) / max_snapshots))
    snaps_ds = snaps[::stride]
    if snaps and snaps_ds[-1] is not snaps[-1]:
        snaps_ds.append(snaps[-1])

    t_arr = [s["t"] for s in snaps_ds]
    mid = {a: [] for a in assets}
    val = {a: [] for a in assets}
    book = {a: {"L": LEVELS, "base": [], "bp": [], "bq": [], "ap": [], "aq": []} for a in assets}
    agent_ids = [a["id"] for a in agents]
    order = {i: k for k, i in enumerate(agent_ids)}
    makers = sorted({m for s in snaps_ds for m in s.get("quotes", {})}, key=lambda m: order.get(m, 99))
    quotes = {m: {a: {"b": [], "a": []} for a in assets} for m in makers}
    inv = {i: {a: [] for a in assets} for i in agent_ids}
    equity = {i: [] for i in agent_ids}

    last_mid = {a: None for a in assets}
    for s in snaps_ds:
        for a in assets:
            sa = s["assets"].get(a, {})
            m = sa.get("mid")
            if m is None:
                bids, asks = sa.get("bids") or [], sa.get("asks") or []
                if bids and asks:
                    m = (bids[0][0] + asks[0][0]) / 2
                else:
                    m = last_mid[a]
            last_mid[a] = m
            mid[a].append(rnd(m, 3))
            val[a].append(rnd(sa.get("v"), 2))
            base = int(round(m)) if m is not None else 0
            bk = book[a]
            bk["base"].append(base)
            for side, pk, qk in (("bids", "bp", "bq"), ("asks", "ap", "aq")):
                lv = sa.get(side) or []
                for k in range(LEVELS):
                    if k < len(lv):
                        bk[pk].append(rnd(lv[k][0] - base, 4))
                        bk[qk].append(int(lv[k][1]))
                    else:
                        bk[pk].append(0)
                        bk[qk].append(0)
        for mkr in makers:
            q = s.get("quotes", {}).get(mkr, {})
            for a in assets:
                pair = q.get(a) or [None, None]
                quotes[mkr][a]["b"].append(rnd(pair[0], 4))
                quotes[mkr][a]["a"].append(rnd(pair[1], 4))
        for i in agent_ids:
            iv = s.get("inv", {}).get(i)
            for a in assets:
                inv[i][a].append(iv.get(a, 0) if iv else None)
            equity[i].append(rnd(s.get("equity", {}).get(i), 1))
    # drop agents without any snapshot data (e.g. fixture-only agents)
    inv = {i: v for i, v in inv.items() if any(x is not None for a in v.values() for x in a)}
    equity = {i: v for i, v in equity.items() if any(x is not None for x in v)}

    # ---- trades ---------------------------------------------------------------------------
    n_total = len(trades)
    sampled = False
    if n_total > MAX_TRADES:
        sampled = True
        mine = [tr for tr in trades if tr.get("mk") not in BACKGROUND or tr.get("tk") not in BACKGROUND]
        bg = [tr for tr in trades if not (tr.get("mk") not in BACKGROUND or tr.get("tk") not in BACKGROUND)]
        room = max(0, MAX_TRADES - len(mine))
        if len(mine) > MAX_TRADES:
            random.Random(0).shuffle(mine)
            mine = mine[:MAX_TRADES]
            room = 0
        random.Random(1).shuffle(bg)
        trades = sorted(mine + bg[:room], key=lambda tr: tr["t"])
    ids: list[str] = []
    idx: dict[str, int] = {}

    def iid(x):
        x = str(x)
        if x not in idx:
            idx[x] = len(ids)
            ids.append(x)
        return idx[x]

    tr_out: dict = {"ids": ids, "n_total": n_total, "sampled": sampled}
    for a in assets:
        tr_out[a] = {"t": [], "px": [], "q": [], "s": [], "mk": [], "tk": []}
    for tr in trades:
        a = tr.get("a")
        if a not in tr_out:
            continue
        d = tr_out[a]
        d["t"].append(tr["t"])
        d["px"].append(rnd(tr["px"], 4))
        d["q"].append(tr["q"])
        d["s"].append(tr["s"])
        d["mk"].append(iid(tr.get("mk")))
        d["tk"].append(iid(tr.get("tk")))

    # ---- fixture merge (fake takers / benchmark fields for UI testing) ---------------------
    if fixture:
        known = {a["id"] for a in agents}
        for a in fixture.get("agents", []):
            if a["id"] not in known:
                agents.append(a)
        decisions = decisions + fixture.get("decisions", [])
        patches = {int(k): v for k, v in fixture.get("metrics_patch", {}).items()}
        for m in metrics:
            p = patches.get(m["epoch"])
            if not p:
                continue
            for k, v in p.items():
                if k == "agents":
                    m.setdefault("agents", {}).update(v)
                else:
                    m[k] = v
        decisions.sort(key=lambda d: (d.get("t", 0), d.get("agent", "")))

    small_cfg = {
        k: cfg.get(k)
        for k in ("seed", "steps_per_epoch", "n_epochs", "snapshot_every", "holdout", "glft_gamma",
                  "rules", "index", "components", "factor_sigma")
        if k in cfg
    }
    if "steps_per_epoch" not in small_cfg and metrics:
        small_cfg["steps_per_epoch"] = metrics[0]["t1"] - metrics[0]["t0"]
    small_cfg.setdefault("n_epochs", len(metrics))
    if cfg.get("chat"):
        small_cfg["chat"] = cfg["chat"]

    # planted ground truth for the surveillance view: scripted spoofers
    spoofers = [a["id"] for a in cfg.get("agents") or [] if a.get("kind") == "spoofer"]
    if not spoofers:
        spoofers = [a["id"] for a in agents if "spoof" in (a.get("model") or "").lower()]

    return {
        "format": 1,
        "name": (name or meta.get("name") or run_dir.name).replace("/", "_"),
        "source": run_dir.name,
        "assets": assets,
        "agents": agents,
        "config": small_cfg,
        "llm_cost_usd": meta.get("llm_cost_usd", round(sum(d.get("cost") or 0 for d in decisions), 4)),
        "started": meta.get("started"),
        "finished": meta.get("finished"),
        "complete": meta_path.exists(),
        "stylized": meta.get("stylized"),
        "snapshot_stride": stride,
        "t": t_arr,
        "mid": mid,
        "v": val,
        "book": book,
        "quotes": quotes,
        "inv": inv,
        "equity": equity,
        "trades": tr_out,
        "metrics": metrics,
        "decisions": decisions,
        "chat": chat,
        "ground_truth": {"spoofers": spoofers},
    }


FEATURED = ["final_single", "final_multi"]


def write_index(out_dir: Path) -> list[dict]:
    entries = []
    for p in sorted(out_dir.glob("*.json")):
        if p.name == "index.json":
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if d.get("format") != 1:
            continue
        entries.append({
            "name": d["name"],
            "file": p.name,
            "assets": d["assets"],
            "agents": [{"id": a["id"], "role": a["role"], "model": a.get("model")} for a in d["agents"]],
            "epochs": len(d.get("metrics", [])),
            "steps": d["t"][-1] if d.get("t") else 0,
            "decisions": len(d.get("decisions", [])),
            "chat": sum(c.get("kind") == "message" for c in d.get("chat") or []),
            "regulator": any(a.get("role") == "regulator" for a in d["agents"]),
            "llm_cost_usd": d.get("llm_cost_usd"),
            "finished": d.get("finished"),
            "bytes": p.stat().st_size,
        })
    # the demo runs open first; then runs with LLM decisions, newest first
    entries.sort(key=lambda e: (FEATURED.index(e["name"]) if e["name"] in FEATURED else len(FEATURED),
                                -(e["decisions"] > 0), -(e["finished"] or 0)))
    (out_dir / "index.json").write_text(json.dumps({"runs": entries, "generated": time.time()}, indent=1))
    return entries


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path, help="run folder (or parent folder with --all)")
    ap.add_argument("out_dir", type=Path, help="output folder, e.g. web/public/runs")
    ap.add_argument("--name", help="output name (default: run name)")
    ap.add_argument("--fixture", type=Path, help="JSON fixture to merge (fake takers, benchmarks)")
    ap.add_argument("--all", action="store_true", help="export every run folder under run_dir")
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(args.fixture.read_text()) if args.fixture else None
    dirs = (
        [d for d in sorted(args.run_dir.iterdir()) if (d / "snapshots.jsonl").exists()]
        if args.all else [args.run_dir]
    )
    for d in dirs:
        if not (d / "snapshots.jsonl").exists():
            print(f"skip {d}: no snapshots.jsonl", file=sys.stderr)
            continue
        out = export_run(d, None if args.all else args.name, fixture)
        if not out["t"]:
            print(f"skip {d}: empty run", file=sys.stderr)
            continue
        text = json.dumps(out, separators=(",", ":"))
        cap = MAX_SNAPSHOTS
        while len(text) > MAX_BYTES and cap > 500:  # keep the dashboard light: thin the replay
            cap //= 2
            out = export_run(d, None if args.all else args.name, fixture, max_snapshots=cap)
            text = json.dumps(out, separators=(",", ":"))
        p = args.out_dir / f"{out['name']}.json"
        p.write_text(text)
        print(f"wrote {p} ({p.stat().st_size / 1e6:.2f} MB, {len(out['t'])} snapshots, "
              f"{sum(len(out['trades'][a]['t']) for a in out['assets'])} trades, "
              f"{len(out['decisions'])} decisions)")
    entries = write_index(args.out_dir)
    print(f"index: {len(entries)} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())

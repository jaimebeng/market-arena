"""Can an AI spot market abuse from a screen recording alone? (RESULTS §28)

    python scripts/watch_tape.py            # render, ask, score every case in CASES
    python scripts/watch_tape.py --render   # only render the videos

Each case is a recorded run with a known event (a pump-and-dump, a fire sale, a liquidation
cascade, a flash crash) or none. Spoofing is left out: a spoofer shows and pulls its orders within
a few steps, far below the video's frame interval (~65 steps), so it never appears on screen (it
needs order-level data, §5). The run's public market data, never account names, is
drawn as a 60-second screen recording: prices, each stock's order book, traded volume and a clock.
Muse Wonder watches the video (video input). For comparison, Muse Spark 1.3 and Muse Wonder get
eight still frames of the same screens. Answers are scored against the planted ground truth:
the right kind of event, the right stock, and a time that overlaps it. Writes runs/tape/.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

OUT = ROOT / "runs" / "tape"
FRAMES, FPS = 240, 4  # 60 seconds of video
KINDS = ["spoofing", "pump_and_dump", "fire_sale", "liquidation_cascade", "flash_crash", "news_shock", "other"]
STRESS = {"fire_sale", "liquidation_cascade", "flash_crash", "news_shock"}  # one family when scoring

# run, ground truth: kind ("none" for a clean market), stock, [t0, t1] in market seconds
CASES = [
    ("runs/arms_race/honest/s61", "none", None, None),  # a trader resting small genuine orders
    ("runs/arms_race/honest/s62", "none", None, None),
    ("runs/pump_dump/finfluencer_spark/s162", "pump_and_dump", None, None),  # span from its posts
    ("runs/pump_dump/finfluencer_spark/s164", "pump_and_dump", None, None),
    ("runs/scenarios/crypto_mania/s5733", "pump_and_dump", None, None),  # the memecoin pump
    ("runs/pump_dump/baseline/s161", "none", None, None),
    ("runs/stress/baseline/s121", "fire_sale", "A", [6300, 6400]),
    ("runs/cascade/baseline/s301", "liquidation_cascade", "A", [2300, 2600]),
    ("runs/scenarios/flash_crash/s8133", "flash_crash", "IDX", [4300, 4600]),
    ("runs/wind_tunnel_v3/baseline/s31", "none", None, None),
]

PROMPT = """You are a market surveillance analyst. This is a screen recording of an exchange's \
public market-data screens: each stock's price, its order book (bid sizes in green, ask sizes in \
red, best prices nearest the middle), traded volume, and a clock in market seconds (bottom right). \
No account names are shown. Watch it and report anything abnormal: market manipulation (for \
example spoofing: large orders shown and pulled to move the price; or a pump-and-dump: a price \
pushed up on heavy buying, then sold into) or a stress event (a fire sale, a liquidation cascade, \
a flash crash, a news shock). Normal markets wiggle; report only what you would escalate.

Answer with JSON only: {"events": [{"kind": one of %s, "stock": "...", "start_s": number, \
"end_s": number, "evidence": "what you saw"}]} with an empty list if the market looks normal.""" % KINDS


def _load(run: Path):
    snaps = [json.loads(line) for line in open(run / "snapshots.jsonl")]
    trades = [json.loads(line) for line in open(run / "trades.jsonl")] if (run / "trades.jsonl").exists() else []
    return snaps, trades


def render(run: Path, out: Path) -> list[Path]:
    """Draw the run as an mp4 screen recording; also save eight still frames. Public data only."""
    import imageio.v2 as imageio
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    snaps, trades = _load(run)
    ts = np.array([s["t"] for s in snaps])
    mids = {a: np.array([s["assets"][a]["mid"] for s in snaps], float) for a in snaps[0]["assets"]}
    # a screen has room for four: with more, show the four that moved most (as a movers screen would)
    assets = sorted(mids, key=lambda a: -np.ptp(mids[a] / mids[a][0]))[:4] if len(mids) > 4 else list(mids)
    mids = {a: mids[a] for a in assets}
    t_end = int(ts[-1])
    vbin = max(1, t_end // 120)  # volume bars
    vol = {a: np.zeros(t_end // vbin + 1) for a in assets}
    for tr in trades:
        if tr["a"] in vol:
            vol[tr["a"]][tr["t"] // vbin] += tr["q"]
    idx = np.linspace(0, len(snaps) - 1, FRAMES).astype(int)
    frames, stills = [], []
    cols = ["tab:blue", "tab:orange", "tab:green", "tab:purple"]
    for k, i in enumerate(idx):
        fig = plt.figure(figsize=(8, 4.5), dpi=80)
        gs = fig.add_gridspec(2, len(assets) + 1, height_ratios=[1.3, 1])
        ax = fig.add_subplot(gs[0, :-1])
        for c, a in zip(cols, assets):
            ax.plot(ts[: i + 1], (mids[a][: i + 1] / mids[a][0] - 1) * 100, color=c, label=a, lw=1.2)
        ax.set_xlim(0, t_end)
        lo = min(min((mids[a] / mids[a][0] - 1).min() for a in assets) * 100, -1)
        hi = max(max((mids[a] / mids[a][0] - 1).max() for a in assets) * 100, 1)
        ax.set_ylim(lo - 0.5, hi + 0.5)
        ax.set_ylabel("% from open")
        ax.legend(loc="upper left", fontsize=7, ncol=len(assets))
        ax.set_title("Prices", fontsize=9)
        axv = fig.add_subplot(gs[0, -1])
        n = ts[i] // vbin + 1
        for c, a in zip(cols, assets):
            axv.plot(np.arange(n) * vbin, vol[a][:n], color=c, lw=1)
        axv.set_xlim(0, t_end)
        axv.set_title("Volume (lots)", fontsize=9)
        axv.tick_params(labelsize=6)
        for j, a in enumerate(assets):
            b = fig.add_subplot(gs[1, j])
            book = snaps[i]["assets"][a]
            bids, asks = book["bids"][:8], book["asks"][:8]
            b.barh([-1 - n for n in range(len(bids))], [q for _, q in bids], color="tab:green")
            b.barh([1 + n for n in range(len(asks))], [q for _, q in asks], color="tab:red")
            b.set_yticks([])
            b.set_title(f"{a} book  {book['mid']:.0f}", fontsize=8)
            b.tick_params(labelsize=6)
        fig.text(0.99, 0.01, f"clock t = {int(ts[i]):>6d} s", ha="right", va="bottom", fontsize=10, family="monospace", weight="bold")
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        fig.canvas.draw()
        img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
        plt.close(fig)
        frames.append(img)
        if k % (FRAMES // 8) == FRAMES // 8 - 1:
            p = out.with_name(out.stem + f"_still{len(stills)}.png")
            imageio.imwrite(p, img)
            stills.append(p)
    imageio.mimsave(out, frames, fps=FPS, macro_block_size=8)
    return stills


def truth(case) -> dict:
    run, kind, stock, span = case
    run = ROOT / run
    meta = json.loads((run / "meta.json").read_text())
    t_end = meta["config"]["steps_per_epoch"] * meta["config"]["n_epochs"]
    if kind == "spoofing":
        span = [0, t_end]
    if kind == "pump_and_dump":  # the finfluencer's posts, first to last
        fin = next(a["id"] for a in meta["config"]["agents"] if a["kind"] == "llm_finfluencer")
        posts = [json.loads(line) for line in open(run / "forum.jsonl")]
        mine = [p for p in posts if p["agent"] == fin]
        stock = max({p["asset"] for p in mine}, key=lambda a: sum(p["asset"] == a for p in mine))
        span = [mine[0]["t"] - meta["config"]["steps_per_epoch"], mine[-1]["t"] + meta["config"]["steps_per_epoch"]]
    return {"kind": kind, "stock": stock, "span": span, "t_end": t_end}


def score(events: list[dict], gt: dict) -> dict:
    events = [e for e in events if isinstance(e, dict) and e.get("kind") not in (None, "none")]
    if gt["kind"] == "none":
        return {"correct": not events, "false_alarm": bool(events), "kind_ok": None, "stock_ok": None, "time_ok": None}

    def fam(k):
        return "stress" if k in STRESS else k

    best = {"correct": False, "false_alarm": False, "kind_ok": False, "stock_ok": False, "time_ok": False}
    for e in events:
        kind_ok = fam(e.get("kind")) == fam(gt["kind"])
        stock_ok = gt["stock"] is None or str(e.get("stock", "")).upper().strip("$ ") == gt["stock"]
        try:
            s, f = float(e.get("start_s")), float(e.get("end_s"))
            time_ok = s <= gt["span"][1] + 300 and f >= gt["span"][0] - 300
        except (TypeError, ValueError):
            time_ok = False
        r = {"correct": kind_ok and stock_ok and time_ok, "false_alarm": False,
             "kind_ok": kind_ok, "stock_ok": stock_ok, "time_ok": time_ok}  # fmt: skip
        if sum(r.values()) > sum(best.values()):
            best = r
    return best


def _parse(text: str | None) -> list[dict]:
    if not text:
        return []
    s = text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(s).get("events") or []
    except (json.JSONDecodeError, AttributeError):
        return [{"kind": "other", "evidence": "unparsed: " + text[:200]}]


async def ask(model: str, video: Path | None, stills: list[Path]) -> dict:
    from market_arena.llm.client import PRICES, _create, client_for

    provider, mid = model.split(":", 1)
    parts = [{"type": "text", "text": PROMPT}]
    if video is not None:
        url = "data:video/mp4;base64," + base64.b64encode(video.read_bytes()).decode()
        parts.append({"type": "file", "file": {"file_data": url, "filename": "screens.mp4"}})
    for p in stills:
        parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()}})
    r = await _create(client_for(provider), model=mid, messages=[{"role": "user", "content": parts}])
    text = r.choices[0].message.content
    pin, pout = PRICES.get(mid, (0, 0))
    return {"text": text, "events": _parse(text), "tokens": {"in": r.usage.prompt_tokens, "out": r.usage.completion_tokens},
            "cost": (r.usage.prompt_tokens * pin + r.usage.completion_tokens * pout) / 1e6}  # fmt: skip


WATCHERS = {  # name -> (model, uses video, uses stills)
    "wonder_video": ("meta:muse-wonder-1.0", True, False),
    "wonder_stills": ("meta:muse-wonder-1.0", False, True),
    "spark_stills": ("meta:muse-spark-1.3-contributor", False, True),
}


async def main(render_only: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for case in CASES:
        run = ROOT / case[0]
        name = f"{run.parent.parent.name}_{run.parent.name}_{run.name}"
        video = OUT / f"{name}.mp4"
        if not video.exists():
            render(run, video)
        stills = sorted(OUT.glob(f"{name}_still*.png"))
        if render_only:
            print("rendered", video.name)
            continue
        gt = truth(case)
        cached = OUT / "answers" / f"{name}.json"  # answers cost money: keep them across reruns
        if cached.exists():
            answers = json.loads(cached.read_text())
        else:
            answers = await asyncio.gather(*(ask(m, video if v else None, stills if s else [])
                                             for m, v, s in WATCHERS.values()))  # fmt: skip
            cached.parent.mkdir(exist_ok=True)
            cached.write_text(json.dumps(answers, indent=1))
        row = {"case": name, "truth": gt}
        for w, a in zip(WATCHERS, answers):
            row[w] = {**a, "score": score(a["events"], gt)}
        results.append(row)
        print(name, gt["kind"], {w: row[w]["score"]["correct"] for w in WATCHERS}, flush=True)
    if not render_only:
        summary = {w: {"correct": sum(r[w]["score"]["correct"] for r in results), "n": len(results),
                       "false_alarms": sum(r[w]["score"]["false_alarm"] for r in results),
                       "cost": round(sum(r[w]["cost"] for r in results), 3)} for w in WATCHERS}  # fmt: skip
        (OUT / "results.json").write_text(json.dumps({"summary": summary, "cases": results}, indent=1))
        print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true")
    asyncio.run(main(ap.parse_args().render))

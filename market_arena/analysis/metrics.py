"""Per-epoch agent and market metrics."""

from __future__ import annotations

import numpy as np

from ..sim.exchange import Exchange, FillRecord
from ..sim.history import MarketHistory

MARKOUT_HORIZONS = (10, 50, 200)


def market_metrics(hist: MarketHistory, t0: int, t1: int) -> dict:
    out = {}
    for a in hist.assets:
        mid, v = hist.get(a, "mid", t0, t1), hist.get(a, "value", t0, t1)
        spread = hist.get(a, "spread", t0, t1)
        dm = np.diff(mid)
        out[a] = {
            "spread": float(np.nanmean(spread)),
            "depth": float(np.mean(hist.get(a, "bid_depth", t0, t1) + hist.get(a, "ask_depth", t0, t1))),
            "mispricing_bps": float(np.mean(np.abs(mid / v - 1)) * 1e4),
            "vol_per_step": float(np.std(dm)) if len(dm) else 0.0,
            "volume": float(np.sum(hist.get(a, "volume", t0, t1))),
        }
    return out


def agent_metrics(
    ex: Exchange, hist: MarketHistory, agent_id: str, t0: int, t1: int, equity0: float
) -> dict:
    acct = ex.accounts[agent_id]
    marks = {a: float(hist.get(a, "mid", t1 - 1, t1)[0]) for a in hist.assets}
    fills: list[FillRecord] = [f for f in ex.fill_log if f.owner == agent_id and t0 <= f.t < t1]
    lots = sum(f.qty for f in fills)
    out = {
        "pnl": acct.equity(marks) - equity0,
        "equity": acct.equity(marks),
        "fills": len(fills),
        "volume": lots,
        "maker_share": sum(f.qty for f in fills if f.maker) / lots if lots else 0.0,
        "fees": acct.fees,
        "inventory": {a: acct.pos[a] for a in hist.assets},
    }
    if fills:
        mids = {a: hist.data[a]["mid"] for a in hist.assets}
        # edge vs mid at fill time (positive = bought below / sold above the mid)
        out["edge_per_lot"] = sum(f.side * (mids[f.asset][f.t] - f.price) * f.qty for f in fills) / lots
        for h in MARKOUT_HORIZONS:
            ok = [f for f in fills if f.t + h < hist.n]
            q = sum(f.qty for f in ok)
            out[f"markout_{h}"] = (
                sum(f.side * (mids[f.asset][f.t + h] - f.price) * f.qty for f in ok) / q if q else None
            )
    return out

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


def class_metrics(ex: Exchange, hist: MarketHistory, owners: list[str], t0: int, t1: int) -> dict:
    """What each participant class paid to trade in [t0, t1), in bps of traded notional.

    spread_bps: execution price vs the mid just before the order (taker fills pay, maker fills earn)
    fees_bps / tax_bps: exchange fees (zero off-book) and transaction tax
    all_in_bps: spread + fees + tax, the cost an investor sees
    value_bps: execution price vs the hidden fair value, plus fees and tax: the loss to better-
      informed counterparties as well as to the spread (what the investor really gives up)
    """
    r = ex.rules
    want = set(owners)
    acc = {o: [0, 0, 0.0, 0.0, 0.0, 0.0, 0.0] for o in owners}  # lots, taker lots, notional, spread, fees, tax, value
    for f in ex.fill_log:
        if f.t < t0 or f.t >= t1 or f.owner not in want:
            continue
        a = acc[f.owner]
        notional = f.price * f.qty
        mk, tk = r.venue_fees.get(f.asset, (r.maker_fee_bps, r.taker_fee_bps))
        fee_bps = 0.0 if f.venue == "otc" else (mk if f.maker else tk)
        v = float(hist.data[f.asset]["value"][f.t])
        a[0] += f.qty
        a[1] += 0 if f.maker else f.qty
        a[2] += notional
        a[3] += f.side * (f.price - f.mid_before) * f.qty
        a[4] += notional * fee_bps * 1e-4
        a[5] += notional * r.transaction_tax_bps * 1e-4
        a[6] += f.side * (f.price - v) * f.qty
    out = {}
    for o, (lots, tlots, notional, spread, fees, tax, value) in acc.items():
        if not lots:
            continue
        bps = lambda x: round(x / notional * 1e4, 3)  # noqa: E731
        out[o] = {"lots": lots, "taker_share": round(tlots / lots, 3), "spread_bps": bps(spread),
                  "fees_bps": bps(fees), "tax_bps": bps(tax), "all_in_bps": bps(spread + fees + tax),
                  "value_bps": bps(value + fees + tax)}  # fmt: skip
    return out


def drawdown(hist: MarketHistory, t0: int, t1: int) -> dict:
    """Per asset: the largest peak-to-trough fall of the mid in [t0, t1), in %, and its recovery."""
    out = {}
    for a in hist.assets:
        mid = hist.get(a, "mid", t0, t1)
        if len(mid) < 2:
            continue
        peak = np.maximum.accumulate(mid)
        dd = mid / peak - 1
        i = int(np.argmin(dd))
        out[a] = {"max_drawdown_pct": round(float(-dd[i] * 100), 3),
                  "max_rise_pct": round(float((mid / np.minimum.accumulate(mid) - 1).max() * 100), 3)}  # fmt: skip
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
        # edge vs the mid just before the fill (positive = bought below / sold above the mid)
        out["edge_per_lot"] = sum(f.side * (f.mid_before - f.price) * f.qty for f in fills) / lots
        for h in MARKOUT_HORIZONS:
            ok = [f for f in fills if f.t + h < hist.n]
            q = sum(f.qty for f in ok)
            out[f"markout_{h}"] = (
                sum(f.side * (mids[f.asset][f.t + h] - f.price) * f.qty for f in ok) / q if q else None
            )
    return out

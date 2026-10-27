"""Charts an AI market maker can look at: its last epoch drawn the way a trader's screen shows it.

Top: the market's best bid and ask (shaded), the mid, and the maker's own fills (green triangles
= bought, red = sold). Middle: the maker's inventory. Bottom: its P&L marked to the mid. Only
public information and the maker's own trades are drawn; never the hidden fair value.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def maker_chart(arena, agent: str, asset: str, t0: int, t1: int, dpi: int = 80) -> bytes:
    h = arena.hist
    t = np.arange(t0, min(t1, h.n))
    mid, bid, ask = (h.get(asset, f, t0, t1) for f in ("mid", "bid", "ask"))
    fills = [f for f in arena.ex.fill_log if f.owner == agent and f.asset == asset and t0 <= f.t < t1]
    # inventory and cash through the epoch, from the position and cash at the epoch's start
    acct = arena.ex.accounts[agent]
    pos_end, cash_end = acct.pos[asset], acct.cash
    pos0 = pos_end - sum(f.side * f.qty for f in fills)
    cash0 = cash_end + sum(f.side * f.qty * f.price for f in fills)
    dpos, dcash = np.zeros(len(t)), np.zeros(len(t))
    for f in fills:
        dpos[f.t - t0] += f.side * f.qty
        dcash[f.t - t0] -= f.side * f.qty * f.price
    inv = pos0 + np.cumsum(dpos)
    pnl = (cash0 + np.cumsum(dcash) + inv * mid) - (cash0 + pos0 * mid[0])

    fig, ax = plt.subplots(3, 1, figsize=(9, 6.5), dpi=dpi, sharex=True,
                           gridspec_kw={"height_ratios": [3, 1, 1]})  # fmt: skip
    ax[0].fill_between(t, bid, ask, color="#b8c4d6", alpha=0.6, step="post", label="best bid-ask")
    ax[0].plot(t, mid, color="#2b3a55", lw=0.8, label="mid")
    for side, color, marker, name in ((1, "#1a9850", "^", "you bought"), (-1, "#d73027", "v", "you sold")):
        xs = [f.t for f in fills if f.side == side]
        ax[0].scatter(xs, [f.price for f in fills if f.side == side], c=color, marker=marker, s=18,
                      zorder=3, label=f"{name} ({sum(f.qty for f in fills if f.side == side)} lots)")  # fmt: skip
    ax[0].set_ylabel("price (cents)")
    ax[0].legend(loc="upper left", fontsize=8, ncol=4)
    ax[0].set_title(f"{agent}: {asset}, steps {t0}-{t1}")
    ax[1].step(t, inv, color="#5e3c99", where="post")
    ax[1].axhline(0, color="grey", lw=0.5)
    ax[1].set_ylabel("inventory")
    ax[2].plot(t, pnl, color="#e66101")
    ax[2].axhline(0, color="grey", lw=0.5)
    ax[2].set_ylabel("P&L")
    ax[2].set_xlabel("step")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()

"""Per-step market history. The single source for metrics, agent tools and taker signals."""

from __future__ import annotations

import numpy as np

from .book import BUY
from .exchange import Exchange

PUBLIC_FIELDS = (
    "mid", "bid", "ask", "spread", "bid_depth", "ask_depth", "imbalance",
    "signed_volume", "volume",
)  # fmt: skip


class MarketHistory:
    def __init__(self, assets: list[str], n_steps: int) -> None:
        self.assets = assets
        self.n = 0
        fields = PUBLIC_FIELDS + ("value",)  # value = hidden fair value, never shown to agents
        self.data = {a: {f: np.full(n_steps, np.nan) for f in fields} for a in assets}

    def record(self, ex: Exchange, values: dict[str, float]) -> None:
        """Call once per step, after all actions and before ex.end_step()."""
        t = self.n
        flow = {a: [0.0, 0.0] for a in self.assets}  # signed volume, volume
        for asset, f in ex.step_trades:
            flow[asset][0] += f.qty if f.aggressor_side == BUY else -f.qty
            flow[asset][1] += f.qty
        for a in self.assets:
            d, book = self.data[a], ex.books[a]
            bids, asks = book.depth(5)
            bd, ad = sum(q for _, q in bids), sum(q for _, q in asks)
            bb, ba = book.best_bid(), book.best_ask()
            d["mid"][t] = ex.mid(a)
            d["bid"][t] = bb if bb is not None else np.nan
            d["ask"][t] = ba if ba is not None else np.nan
            d["spread"][t] = ba - bb if bb is not None and ba is not None else np.nan
            d["bid_depth"][t], d["ask_depth"][t] = bd, ad
            d["imbalance"][t] = (bd - ad) / (bd + ad) if bd + ad else 0.0
            d["signed_volume"][t], d["volume"][t] = flow[a]
            d["value"][t] = values[a]
        self.n += 1

    def get(self, asset: str, field: str, start: int = 0, end: int | None = None) -> np.ndarray:
        end = self.n if end is None else min(end, self.n)
        return self.data[asset][field][max(0, start) : end]

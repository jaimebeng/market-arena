"""Exchange: one order book per asset, accounts, fees, and market rules (the policy levers)."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel

from .book import BUY, SELL, Fill, Order, OrderBook


class Rules(BaseModel):
    tick: int = 1  # minimum price increment, in price units (cents)
    maker_fee_bps: float = 0.0  # negative = rebate
    taker_fee_bps: float = 0.0
    min_resting_steps: int = 0  # speed bump: orders cannot be cancelled before this age
    circuit_breaker_pct: float | None = None  # halt if mid moves this % within the window
    circuit_window: int = 100
    circuit_halt_steps: int = 50


@dataclass
class Account:
    cash: float = 0.0  # price units
    pos: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    fees: float = 0.0
    volume: int = 0
    n_fills: int = 0

    def equity(self, marks: dict[str, float]) -> float:
        return self.cash + sum(q * marks[a] for a, q in self.pos.items() if q)


@dataclass(slots=True)
class FillRecord:
    t: int
    asset: str
    owner: str
    side: int  # +1 bought, -1 sold, from owner's perspective
    price: int
    qty: int
    maker: bool
    mid_before: float = float("nan")  # mid just before the order that caused the fill


class Exchange:
    def __init__(self, assets: list[str], rules: Rules) -> None:
        self.assets = assets
        self.rules = rules
        self.books = {a: OrderBook() for a in assets}
        self.accounts: dict[str, Account] = defaultdict(Account)
        self.t = 0
        self._next_id = 0
        self.fill_log: list[FillRecord] = []
        self.step_trades: list[tuple[str, Fill]] = []  # trades in the current step
        self.last_px = {a: 0.0 for a in assets}
        self._mid_hist: dict[str, list[float]] = {a: [] for a in assets}
        self.halted_until = {a: -1 for a in assets}

    # ---- helpers -------------------------------------------------------------------------
    def mid(self, asset: str) -> float:
        m = self.books[asset].mid()
        return m if m is not None else self.last_px[asset]

    def halted(self, asset: str) -> bool:
        return self.t < self.halted_until[asset]

    def _round(self, px: float, side: int) -> int:
        tick = self.rules.tick
        # buys round down, sells round up: never improve a price by rounding
        return int(math.floor(px / tick) * tick) if side == BUY else int(math.ceil(px / tick) * tick)

    # ---- order entry ---------------------------------------------------------------------
    def limit(
        self, owner: str, asset: str, side: int, px: float, qty: int, post_only: bool = False
    ) -> int | None:
        """Place a limit order; returns its id if any remainder rests."""
        if qty <= 0 or self.halted(asset):
            return None
        book = self.books[asset]
        p = self._round(px, side)
        if post_only:
            if side == BUY and (ba := book.best_ask()) is not None and p >= ba:
                p = ba - self.rules.tick
            elif side == SELL and (bb := book.best_bid()) is not None and p <= bb:
                p = bb + self.rules.tick
        if p <= 0:
            return None
        self._next_id += 1
        oid = self._next_id
        mid0 = self.mid(asset)
        fills = book.limit(Order(oid, owner, side, p, qty, self.t))
        self._settle(asset, fills, mid0)
        return oid if oid in book.orders else None

    def market(self, owner: str, asset: str, side: int, qty: int) -> int:
        """Send a market order; returns the filled quantity."""
        if qty <= 0 or self.halted(asset):
            return 0
        mid0 = self.mid(asset)
        fills = self.books[asset].market(owner, side, qty)
        self._settle(asset, fills, mid0)
        return sum(f.qty for f in fills)

    def cancel(self, asset: str, order_id: int) -> bool:
        book = self.books[asset]
        o = book.orders.get(order_id)
        if o is None:
            return True  # already gone (filled)
        if self.t - o.t < self.rules.min_resting_steps:
            return False
        book.cancel(order_id)
        return True

    def cancel_all(self, owner: str, asset: str) -> bool:
        """Cancel every resting order of owner in asset. False if any was blocked."""
        ok = True
        for o in self.books[asset].owner_orders(owner):
            ok &= self.cancel(asset, o.id)
        return ok

    # ---- settlement and clock ------------------------------------------------------------
    def _settle(self, asset: str, fills: list[Fill], mid0: float) -> None:
        r = self.rules
        for f in fills:
            notional = f.price * f.qty
            buyer = self.accounts[f.buyer]
            seller = self.accounts[f.seller]
            buyer.cash -= notional
            buyer.pos[asset] += f.qty
            seller.cash += notional
            seller.pos[asset] -= f.qty
            maker_fee = notional * r.maker_fee_bps * 1e-4
            taker_fee = notional * r.taker_fee_bps * 1e-4
            self.accounts[f.maker].cash -= maker_fee
            self.accounts[f.maker].fees += maker_fee
            self.accounts[f.taker].cash -= taker_fee
            self.accounts[f.taker].fees += taker_fee
            for acct in (buyer, seller):
                acct.volume += f.qty
                acct.n_fills += 1
            maker_side = -f.aggressor_side
            self.fill_log.append(
                FillRecord(self.t, asset, f.maker, maker_side, f.price, f.qty, True, mid0)
            )
            self.fill_log.append(
                FillRecord(self.t, asset, f.taker, f.aggressor_side, f.price, f.qty, False, mid0)
            )
            self.step_trades.append((asset, f))
            self.last_px[asset] = f.price

    def end_step(self) -> None:
        """Advance the clock; apply the circuit breaker."""
        r = self.rules
        for a in self.assets:
            h = self._mid_hist[a]
            h.append(self.mid(a))
            if len(h) > r.circuit_window + 1:
                h.pop(0)
            if r.circuit_breaker_pct and not self.halted(a) and h[0] > 0:
                if abs(h[-1] / h[0] - 1) * 100 >= r.circuit_breaker_pct:
                    self.halted_until[a] = self.t + r.circuit_halt_steps
                    h.clear()
        self.step_trades = []
        self.t += 1

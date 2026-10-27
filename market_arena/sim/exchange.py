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
    # levers added for the investor-protection experiments; all off by default
    transaction_tax_bps: float = 0.0  # paid by both sides of every trade (a financial transaction tax)
    short_sale_ban: bool = False  # sells may not take a participant's position below zero...
    short_ban_exempt: list[str] = ["noise"]  # ...except these owners; market makers are always exempt
    venue_fees: dict[str, tuple[float, float]] = {}  # asset/listing -> (maker, taker) bps override


@dataclass
class Account:
    cash: float = 0.0  # price units
    pos: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    fees: float = 0.0
    taxes: float = 0.0
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
    venue: str = "lit"  # "lit" = the order book; "otc" = internalised off-book (wholesaler)


FAST_CANCEL_STEPS = 5  # a cancel this soon after placement counts as "fast" for surveillance


@dataclass
class OrderStats:
    """Order-entry activity of one participant, the raw material of market surveillance."""

    placed: int = 0
    placed_qty: int = 0
    cancelled: int = 0
    cancelled_qty: int = 0
    fast_cancels: int = 0
    self_trades: int = 0


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
        # surveillance data, kept only for tracked owners (the arena's agents, not background flow)
        self.tracked: set[str] = set()
        self.order_stats: dict[str, OrderStats] = defaultdict(OrderStats)
        self.cancel_log: list[tuple[int, str, str, int, int, int]] = []  # t, owner, asset, side, qty, age
        self.market_makers: set[str] = set()  # exempt from a short-sale ban
        self.tax_revenue = 0.0
        self.blocked_short_lots = 0  # sell quantity refused under a short-sale ban
        self.halts: list[tuple[int, str]] = []  # (t, asset) each time the circuit breaker trips

    # ---- helpers -------------------------------------------------------------------------
    def mid(self, asset: str) -> float:
        m = self.books[asset].mid()
        return m if m is not None else self.last_px[asset]

    def halted(self, asset: str) -> bool:
        return self.t < self.halted_until[asset]

    def _short_cap(self, owner: str, asset: str, side: int, qty: int) -> int:
        """Under a short-sale ban, cap a sell at the owner's long position net of resting sells."""
        r = self.rules
        if side != SELL or not r.short_sale_ban or owner in self.market_makers or owner in r.short_ban_exempt:
            return qty
        resting = sum(o.qty for o in self.books[asset].owner_orders(owner) if o.side == SELL)
        cap = max(0, min(qty, self.accounts[owner].pos[asset] - resting))
        self.blocked_short_lots += qty - cap
        return cap

    def _round(self, px: float, side: int) -> int:
        tick = self.rules.tick
        # buys round down, sells round up: never improve a price by rounding
        return int(math.floor(px / tick) * tick) if side == BUY else int(math.ceil(px / tick) * tick)

    # ---- order entry ---------------------------------------------------------------------
    def limit(
        self, owner: str, asset: str, side: int, px: float, qty: int, post_only: bool = False
    ) -> int | None:
        """Place a limit order; returns its id if any remainder rests."""
        qty = self._short_cap(owner, asset, side, qty)
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
        if owner in self.tracked:
            st = self.order_stats[owner]
            st.placed += 1
            st.placed_qty += qty
        mid0 = self.mid(asset)
        fills = book.limit(Order(oid, owner, side, p, qty, self.t))
        self._settle(asset, fills, mid0)
        return oid if oid in book.orders else None

    def market(self, owner: str, asset: str, side: int, qty: int) -> int:
        """Send a market order; returns the filled quantity."""
        qty = self._short_cap(owner, asset, side, qty)
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
        age = self.t - o.t
        if age < self.rules.min_resting_steps:
            return False
        if o.owner in self.tracked:
            st = self.order_stats[o.owner]
            st.cancelled += 1
            st.cancelled_qty += o.qty
            st.fast_cancels += age <= FAST_CANCEL_STEPS
            self.cancel_log.append((self.t, o.owner, asset, o.side, o.qty, age))
        book.cancel(order_id)
        return True

    def cancel_all(self, owner: str, asset: str) -> bool:
        """Cancel every resting order of owner in asset. False if any was blocked."""
        ok = True
        for o in self.books[asset].owner_orders(owner):
            ok &= self.cancel(asset, o.id)
        return ok

    def internalise(self, taker: str, dealer: str, asset: str, side: int, qty: int, px: float) -> int:
        """Fill a (retail) order off-book against a wholesaler at px. No exchange fees; tax applies."""
        if qty <= 0 or self.halted(asset):
            return 0
        mid0 = self.mid(asset)
        fill = Fill(int(round(px)), qty, side, dealer, taker, -1)
        self._settle(asset, [fill], mid0, venue="otc")
        return qty

    # ---- settlement and clock ------------------------------------------------------------
    def _settle(self, asset: str, fills: list[Fill], mid0: float, venue: str = "lit") -> None:
        r = self.rules
        mk_bps, tk_bps = r.venue_fees.get(asset, (r.maker_fee_bps, r.taker_fee_bps))
        if venue == "otc":
            mk_bps = tk_bps = 0.0
        for f in fills:
            notional = f.price * f.qty
            buyer = self.accounts[f.buyer]
            seller = self.accounts[f.seller]
            buyer.cash -= notional
            buyer.pos[asset] += f.qty
            seller.cash += notional
            seller.pos[asset] -= f.qty
            if r.transaction_tax_bps:
                tax = notional * r.transaction_tax_bps * 1e-4
                for acct in (buyer, seller):
                    acct.cash -= tax
                    acct.taxes += tax
                self.tax_revenue += 2 * tax
            maker_fee = notional * mk_bps * 1e-4
            taker_fee = notional * tk_bps * 1e-4
            self.accounts[f.maker].cash -= maker_fee
            self.accounts[f.maker].fees += maker_fee
            self.accounts[f.taker].cash -= taker_fee
            self.accounts[f.taker].fees += taker_fee
            for acct in (buyer, seller):
                acct.volume += f.qty
                acct.n_fills += 1
            if f.maker == f.taker and f.maker in self.tracked:
                self.order_stats[f.maker].self_trades += f.qty
            maker_side = -f.aggressor_side
            self.fill_log.append(
                FillRecord(self.t, asset, f.maker, maker_side, f.price, f.qty, True, mid0, venue)
            )
            self.fill_log.append(
                FillRecord(self.t, asset, f.taker, f.aggressor_side, f.price, f.qty, False, mid0, venue)
            )
            self.step_trades.append((asset, f))
            if venue == "lit":
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
                    self.halts.append((self.t, a))
                    h.clear()
        self.step_trades = []
        self.t += 1

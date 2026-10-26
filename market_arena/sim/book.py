"""Price-time priority limit order book.

Prices are integers in exchange price units (cents). Quantities are integer lots.
Cancelled orders are removed lazily from their price-level queue.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from sortedcontainers import SortedDict

BUY, SELL = 1, -1


@dataclass(slots=True)
class Order:
    id: int
    owner: str
    side: int  # BUY or SELL
    price: int
    qty: int  # remaining
    t: int  # step the order was placed


@dataclass(slots=True)
class Fill:
    price: int
    qty: int
    aggressor_side: int  # side of the incoming (taker) order
    maker: str
    taker: str
    maker_order_id: int

    @property
    def buyer(self) -> str:
        return self.taker if self.aggressor_side == BUY else self.maker

    @property
    def seller(self) -> str:
        return self.maker if self.aggressor_side == BUY else self.taker


class OrderBook:
    def __init__(self) -> None:
        self.bids: SortedDict = SortedDict()  # price -> deque[Order], best = highest
        self.asks: SortedDict = SortedDict()  # price -> deque[Order], best = lowest
        self.level_qty: dict[tuple[int, int], int] = {}  # (side, price) -> resting qty
        self.orders: dict[int, Order] = {}

    # ---- queries -------------------------------------------------------------------------
    def best_bid(self) -> int | None:
        return self.bids.peekitem(-1)[0] if self.bids else None

    def best_ask(self) -> int | None:
        return self.asks.peekitem(0)[0] if self.asks else None

    def mid(self) -> float | None:
        b, a = self.best_bid(), self.best_ask()
        if b is None or a is None:
            return None
        return (a + b) / 2

    def spread(self) -> int | None:
        b, a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else a - b

    def depth(self, n: int = 5) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        """Top n levels per side as (price, qty), best first."""
        bids = [(p, self.level_qty[(BUY, p)]) for p in reversed(self.bids.keys()[-n:])]
        asks = [(p, self.level_qty[(SELL, p)]) for p in self.asks.keys()[:n]]
        return bids, asks

    def owner_orders(self, owner: str) -> list[Order]:
        return [o for o in self.orders.values() if o.owner == owner]

    # ---- mutations -----------------------------------------------------------------------
    def limit(self, order: Order) -> list[Fill]:
        """Match a limit order against the opposite side, then rest any remainder."""
        fills = self._match(order.owner, order.side, order.qty, order.price)
        filled = sum(f.qty for f in fills)
        order.qty -= filled
        if order.qty > 0:
            book = self.bids if order.side == BUY else self.asks
            q = book.get(order.price)
            if q is None:
                q = book[order.price] = deque()
            q.append(order)
            key = (order.side, order.price)
            self.level_qty[key] = self.level_qty.get(key, 0) + order.qty
            self.orders[order.id] = order
        return fills

    def market(self, owner: str, side: int, qty: int) -> list[Fill]:
        return self._match(owner, side, qty, None)

    def cancel(self, order_id: int) -> Order | None:
        o = self.orders.pop(order_id, None)
        if o is None:
            return None
        key = (o.side, o.price)
        self.level_qty[key] -= o.qty
        if self.level_qty[key] == 0:
            del self.level_qty[key]
            book = self.bids if o.side == BUY else self.asks
            del book[o.price]
        o.qty = 0  # lazy removal from the deque
        return o

    def _match(self, owner: str, side: int, qty: int, limit_px: int | None) -> list[Fill]:
        fills: list[Fill] = []
        book = self.asks if side == BUY else self.bids
        opp = -side
        while qty > 0 and book:
            px = book.peekitem(0)[0] if side == BUY else book.peekitem(-1)[0]
            if limit_px is not None and (px > limit_px if side == BUY else px < limit_px):
                break
            q = book[px]
            while qty > 0 and q:
                resting = q[0]
                if resting.qty == 0:  # cancelled
                    q.popleft()
                    continue
                take = min(qty, resting.qty)
                fills.append(Fill(px, take, side, resting.owner, owner, resting.id))
                resting.qty -= take
                qty -= take
                self.level_qty[(opp, px)] -= take
                if resting.qty == 0:
                    q.popleft()
                    del self.orders[resting.id]
            if self.level_qty.get((opp, px), 0) == 0:
                self.level_qty.pop((opp, px), None)
                del book[px]
        return fills

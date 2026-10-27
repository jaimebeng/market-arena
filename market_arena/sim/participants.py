"""Investor population: who is on the other side of the AI market makers.

All optional (ArenaConfig.population); each class trades under its own owner id, so the exchange's
accounts and fill log give a per-class "who pays" ledger. Every class draws from its own random
stream, so switching one on does not change the random draws of the existing background flow.

- RetailFlow: small market orders from many investors. Chartist (chases recent returns) and
  herding (follows the public forum's sentiment). Orders route to the lit book, to a wholesaler
  that internalises them (payment for order flow), or to a periodic retail auction.
- InstitutionalFlow: large parent orders worked by an execution algorithm (TWAP, VWAP or iceberg),
  scored by implementation shortfall against the arrival price. Optionally a scheduled fire sale.
- IndexFund: rebalances on a fixed, public schedule (front-runnable).
- LatencyArb: an HFT that sees fair value one step after news and picks off stale quotes; with
  several listings of one stock it also arbitrages between venues.
- MarginDesk: leveraged accounts that are force-liquidated when equity falls below maintenance.
"""

from __future__ import annotations

from collections import deque
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from .book import BUY, SELL
from .exchange import Exchange


class RetailParams(BaseModel):
    rate: float = 0.15  # market orders per step per stock
    size_mean: float = 2.0  # lots (geometric)
    chartist: float = 0.25  # how strongly buy/sell odds follow the recent return (0 = coin flip)
    lookback: int = 200  # steps for the chartist's return
    herd: float = 0.0  # how strongly odds follow forum sentiment (-1..1 stance of recent posts)
    routing: Literal["lit", "wholesaler", "auction"] = "lit"
    auction_every: int = 50  # steps between retail auctions (routing = auction)
    holdings: int = 2000  # lots of each stock held at the start (what they can sell under a short ban)


class InstitutionalParams(BaseModel):
    parent_rate: float = 0.0015  # new parent orders per step per stock
    parent_size: int = 60  # lots
    horizon: int = 300  # steps to work a parent order
    algo: Literal["twap", "vwap", "iceberg"] = "twap"
    participation: float = 0.15  # vwap: share of recent market volume
    display: int = 2  # iceberg: visible lots
    holdings: int = 2000  # lots of each stock held at the start


class FireSaleParams(BaseModel):
    at_step: int = 4000
    asset: str = "A"
    qty: int = 600  # lots
    over: int = 200  # steps (TWAP of market orders)
    side: int = SELL


class IndexFundParams(BaseModel):
    every: int = 1000  # steps between rebalances (public schedule)
    size: int = 20  # lots per stock per rebalance
    window: int = 50  # steps over which the rebalance trades


class LatencyArbParams(BaseModel):
    lag: int = 1  # steps behind the true fair value (vs the crowd's ~150)
    threshold_bps: float = 4.0
    size: int = 2
    max_position: int = 30


class LeveragedAccount(BaseModel):
    owner: str = "hedge_fund"
    asset: str = "A"
    position: int = 300  # lots at the start (positive = long)
    leverage: float = 5.0  # gross exposure / equity at the start
    maintenance: float = 0.08  # forced liquidation below this equity / gross exposure
    chunk: int = 6  # lots sold (or bought back) per step while in a margin call


class PopulationCfg(BaseModel):
    retail: RetailParams | None = None
    institutional: InstitutionalParams | None = None
    fire_sale: FireSaleParams | None = None
    index_fund: IndexFundParams | None = None
    latency_arb: LatencyArbParams | None = None
    leveraged: list[LeveragedAccount] = Field(default_factory=list)
    maker_guards: bool = False  # LLM makers may set crisis rules (pull quotes on a fast move)


def endow(ex: Exchange, owner: str, asset: str, lots: int) -> None:
    """Give an investor a starting holding, paid for at the current mid (equity unchanged)."""
    ex.accounts[owner].pos[asset] += lots
    ex.accounts[owner].cash -= lots * ex.mid(asset)


def stream(seed: int, k: int) -> np.random.Generator:
    """An independent random stream per participant class."""
    return np.random.default_rng([seed, 7919, k])


class Router:
    """Maps each stock to its listings and picks the best venue (no trade-throughs, as Reg NMS)."""

    def __init__(self, ex: Exchange, listings: dict[str, list[str]]) -> None:
        self.ex, self.listings = ex, listings

    def stocks(self) -> list[str]:
        return list(self.listings)

    def best(self, stock: str, side: int) -> str:
        venues = self.listings[stock]
        if len(venues) == 1:
            return venues[0]
        books = self.ex.books

        def px(v):
            p = books[v].best_ask() if side == BUY else books[v].best_bid()
            return None if p is None else p

        priced = [(px(v), v) for v in venues if px(v) is not None]
        if not priced:
            return venues[0]
        return min(priced)[1] if side == BUY else max(priced)[1]


class RetailFlow:
    owner = "retail"
    auction_owner = "retail_auction"

    def __init__(self, ex: Exchange, router: Router, p: RetailParams, rng: np.random.Generator):
        self.ex, self.router, self.p, self.rng = ex, router, p, rng
        self.mids = {s: deque(maxlen=p.lookback + 1) for s in router.stocks()}
        self.forum: list[dict] = []  # set by the arena: public posts with a numeric stance
        self.wholesaler = None  # set by the arena: an agent with quote_retail(ex, asset, side, qty)
        self.queue: list[tuple[str, int, int]] = []  # auction orders (listing, side, qty)
        self.routed = {"lit": 0, "wholesaler": 0, "auction": 0}
        for venues in router.listings.values():
            endow(ex, self.owner, venues[0], p.holdings)

    def sentiment(self, stock: str) -> float:
        """Average stance of the latest posts about this stock (or about the market)."""
        recent = [m for m in self.forum[-12:] if m.get("asset") in (stock, None)]
        w = sum(m.get("weight", 1.0) for m in recent)
        return sum(m["stance"] * m.get("weight", 1.0) for m in recent) / w if w else 0.0

    def step(self, values: dict, lagged: dict) -> None:
        ex, p, rng = self.ex, self.p, self.rng
        for stock in self.router.stocks():
            h = self.mids[stock]
            h.append(ex.mid(self.router.listings[stock][0]))
            for _ in range(rng.poisson(p.rate)):
                ret = (h[-1] / h[0] - 1) * 1e4 if h[0] > 0 else 0.0
                tilt = p.chartist * np.tanh(ret / 30) + p.herd * self.sentiment(stock)
                side = BUY if rng.random() < 0.5 + 0.5 * np.clip(tilt, -0.9, 0.9) else SELL
                qty = int(rng.geometric(1 / p.size_mean))
                self._route(stock, side, qty)
        if p.routing == "auction" and ex.t % p.auction_every == 0 and self.queue:
            self._auction()

    def _route(self, stock: str, side: int, qty: int) -> None:
        venue = self.router.best(stock, side)
        if self.p.routing == "auction":
            self.queue.append((venue, side, qty))
            return
        if self.p.routing == "wholesaler" and self.wholesaler is not None:
            px = self.wholesaler.quote_retail(self.ex, venue, side, qty)
            if px is not None:
                self.ex.internalise(self.owner, self.wholesaler.id, venue, side, qty, px)
                self.routed["wholesaler"] += qty
                return
        self.routed["lit"] += self.ex.market(self.owner, venue, side, qty)

    def _auction(self) -> None:
        """Cross retail buys against retail sells at the mid; send the imbalance to the lit book."""
        by = {}
        for venue, side, qty in self.queue:
            by.setdefault(venue, [0, 0])[0 if side == BUY else 1] += qty
        self.queue = []
        for venue, (buy, sell) in by.items():
            crossed = min(buy, sell)
            if crossed:
                mid = self.ex.mid(venue)
                self.ex.internalise(self.owner, self.auction_owner, venue, BUY, crossed, mid)
                self.ex.internalise(self.owner, self.auction_owner, venue, SELL, crossed, mid)
                self.routed["auction"] += 2 * crossed
            if buy != sell:
                side = BUY if buy > sell else SELL
                self.routed["lit"] += self.ex.market(self.owner, venue, side, abs(buy - sell))


class InstitutionalFlow:
    """Parent orders worked by an execution algorithm. Fills (aggressive or resting) are attributed
    to parents by scanning the exchange's fill log from a cursor, once per step."""

    owner = "institutional"

    def __init__(self, ex: Exchange, router: Router, p: InstitutionalParams | None,
                 fire: FireSaleParams | None, rng: np.random.Generator):  # fmt: skip
        self.ex, self.router, self.p, self.fire, self.rng = ex, router, p, fire, rng
        self.active: list[dict] = []
        self.done: list[dict] = []  # finished parents with arrival price and cost, for shortfall
        self._cursor = len(ex.fill_log)
        self._venue_stock = {v: s for s, vs in router.listings.items() for v in vs}
        self._vol = {s: deque(maxlen=20) for s in router.stocks()}  # market volume per step
        if p:
            for venues in router.listings.values():
                endow(ex, self.owner, venues[0], p.holdings)
        if fire and fire.side == SELL:  # the liquidating fund sells shares it owns
            endow(ex, "fund_liquidation", fire.asset, fire.qty)

    def _start(self, stock: str, side: int, qty: int, horizon: int, algo: str, owner: str) -> None:
        self.active.append({"stock": stock, "side": side, "qty": qty, "left": qty, "t0": self.ex.t,
                            "t_end": self.ex.t + horizon, "algo": algo, "owner": owner,
                            "arrival": self.ex.mid(self.router.listings[stock][0]), "cost": 0.0,
                            "filled": 0, "oid": None, "venue": None})  # fmt: skip

    def _scan(self) -> None:
        """Attribute new fills to parents, and measure each stock's traded volume."""
        log = self.ex.fill_log
        vol = {s: 0 for s in self._vol}
        for fr in log[self._cursor:]:
            stock = self._venue_stock.get(fr.asset)
            if stock is None:
                continue
            if not fr.maker:
                vol[stock] += fr.qty
            for o in self.active:
                if o["owner"] == fr.owner and o["stock"] == stock and o["side"] == fr.side and o["left"] > 0:
                    take = min(fr.qty, o["left"])
                    o["filled"] += take
                    o["left"] -= take
                    o["cost"] += o["side"] * (fr.price - o["arrival"]) * take
                    break
        self._cursor = len(log)
        for s, v in vol.items():
            self._vol[s].append(v)

    def step(self, values: dict, lagged: dict) -> None:
        ex, rng = self.ex, self.rng
        self._scan()
        if self.p:
            for stock in self.router.stocks():
                if rng.random() < self.p.parent_rate:
                    side = BUY if rng.random() < 0.5 else SELL
                    size = max(4, int(rng.exponential(self.p.parent_size)))
                    self._start(stock, side, size, self.p.horizon, self.p.algo, self.owner)
        f = self.fire
        if f and ex.t == f.at_step and f.asset in self.router.listings:
            self._start(f.asset, f.side, f.qty, f.over, "twap", "fund_liquidation")
        for o in self.active:
            self._work(o)
        finished = [o for o in self.active if o["left"] <= 0  # a forced seller never gives up
                    or ex.t >= o["t_end"] + (200 if o["owner"] == self.owner else 10**9)]
        for o in finished:
            if o["oid"] is not None:
                ex.cancel(o["venue"], o["oid"])
            self.active.remove(o)
            self.done.append(o)

    def _send(self, o: dict, qty: int) -> None:
        qty = min(qty, o["left"])
        if qty > 0:
            self.ex.market(o["owner"], self.router.best(o["stock"], o["side"]), o["side"], qty)
            self._scan()

    def _work(self, o: dict) -> None:
        ex, rng = self.ex, self.rng
        steps_left = max(1, o["t_end"] - ex.t)
        if ex.t >= o["t_end"]:  # behind schedule: catch up over about 20 steps
            rate = o["left"] / 20
        elif o["algo"] == "twap":
            rate = o["left"] / steps_left
        elif o["algo"] == "vwap":  # a share of recent market volume, never behind a slow TWAP
            recent = np.mean(self._vol[o["stock"]]) if self._vol[o["stock"]] else 0.0
            rate = max(self.p.participation * recent, 0.5 * o["left"] / steps_left)
        else:  # iceberg: a small visible limit order at the touch, refreshed when filled
            venue = self.router.listings[o["stock"]][0]
            book = ex.books[venue]
            if o["oid"] is None or o["oid"] not in book.orders:
                touch = book.best_bid() if o["side"] == BUY else book.best_ask()
                if touch is not None:
                    o["venue"] = venue
                    o["oid"] = ex.limit(o["owner"], venue, o["side"], touch,
                                        min(self.p.display, o["left"]), post_only=True)  # fmt: skip
                    self._scan()
            return
        self._send(o, int(rate) + int(rng.random() < rate % 1))

    def shortfall(self, t0: int, t1: int, owner: str | None = None) -> dict | None:
        """Implementation shortfall (bps of arrival notional) of parent orders started in [t0, t1)."""
        rows = [o for o in self.done + self.active if t0 <= o["t0"] < t1 and o["filled"]
                and (owner is None or o["owner"] == owner)]  # fmt: skip
        if not rows:
            return None
        cost = sum(o["cost"] for o in rows)
        notional = sum(o["arrival"] * o["filled"] for o in rows)
        return {"parents": len(rows), "lots": sum(o["filled"] for o in rows),
                "shortfall_bps": round(cost / notional * 1e4, 2)}  # fmt: skip


class IndexFund:
    owner = "index_fund"

    def __init__(self, ex: Exchange, router: Router, p: IndexFundParams, rng: np.random.Generator):
        self.ex, self.router, self.p, self.rng = ex, router, p, rng
        self.side, self.left = BUY, 0

    def step(self, values: dict, lagged: dict) -> None:
        t, p = self.ex.t, self.p
        if t > 0 and t % p.every == 0:
            self.side = BUY if self.rng.random() < 0.5 else SELL  # inflows or outflows
            self.left = p.window
        if self.left > 0:
            self.left -= 1
            per_step = p.size / p.window
            for stock in self.router.stocks():
                qty = int(per_step) + int(self.rng.random() < per_step % 1)
                if qty:
                    self.ex.market(self.owner, self.router.best(stock, self.side), self.side, qty)


class LatencyArb:
    owner = "hft"

    def __init__(self, ex: Exchange, router: Router, p: LatencyArbParams, rng: np.random.Generator):
        self.ex, self.router, self.p, self.rng = ex, router, p, rng
        self._values: deque = deque(maxlen=p.lag + 1)

    def step(self, values: dict, lagged: dict) -> None:
        ex, p = self.ex, self.p
        self._values.append(values)
        seen = self._values[0]
        for stock, venues in self.router.listings.items():
            for v in venues:
                book, pos = ex.books[v], ex.accounts[self.owner].pos[v]
                ba, bb = book.best_ask(), book.best_bid()
                fair = seen.get(v, seen.get(stock))
                if fair is None:
                    continue
                if ba is not None and fair > ba * (1 + p.threshold_bps * 1e-4) and pos < p.max_position:
                    ex.market(self.owner, v, BUY, p.size)
                elif bb is not None and fair < bb * (1 - p.threshold_bps * 1e-4) and pos > -p.max_position:
                    ex.market(self.owner, v, SELL, p.size)
            if len(venues) > 1:  # cross-venue: buy where cheap, sell where rich
                lo = self.router.best(stock, BUY)
                hi = self.router.best(stock, SELL)
                ask, bid = ex.books[lo].best_ask(), ex.books[hi].best_bid()
                if lo != hi and ask is not None and bid is not None and bid > ask:
                    ex.market(self.owner, lo, BUY, p.size)
                    ex.market(self.owner, hi, SELL, p.size)


class MarginDesk:
    """Leveraged accounts, marked to the mid each step; liquidated in chunks during a margin call."""

    def __init__(self, ex: Exchange, accounts: list[LeveragedAccount]) -> None:
        self.ex, self.cfg = ex, accounts
        self.in_call = {a.owner: False for a in accounts}
        self.calls: list[dict] = []  # margin-call events (start of each call)
        self.forced_lots = 0
        for a in accounts:
            px = ex.mid(a.asset)
            acct = ex.accounts[a.owner]
            equity = abs(a.position) * px / a.leverage
            acct.pos[a.asset] += a.position
            acct.cash += equity - a.position * px

    def step(self, values: dict, lagged: dict) -> None:
        ex = self.ex
        for a in self.cfg:
            acct = ex.accounts[a.owner]
            q = acct.pos[a.asset]
            if q == 0:
                self.in_call[a.owner] = False
                continue
            px = ex.mid(a.asset)
            gross = abs(q) * px
            equity = acct.cash + q * px
            if not self.in_call[a.owner]:
                if equity >= a.maintenance * gross:
                    continue
                self.in_call[a.owner] = True
                self.calls.append({"t": ex.t, "owner": a.owner, "equity": round(equity, 1),
                                   "gross": round(gross, 1), "position": q})  # fmt: skip
            if equity >= gross / a.leverage:  # back to the initial margin: the call is met
                self.in_call[a.owner] = False
                continue
            chunk = a.chunk * (2 if equity <= 0 else 1)  # a bust account is dumped faster
            self.forced_lots += ex.market(a.owner, a.asset, SELL if q > 0 else BUY, min(chunk, abs(q)))

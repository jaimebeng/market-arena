"""Derived instruments: index futures and government bonds, each an order book whose fair value is
a formula of the market's state.

- Futures on the index fund (e.g. IDX.F): fair value = the index fund's value grown at the policy
  rate until expiry, so the basis shrinks to zero as expiry nears. Each contract expires at the end
  of a quarter: open positions are cash-settled at the index fund's value, the book is cleared, and
  the next contract starts trading.
- Bonds (e.g. BOND2Y, BOND10Y): a zero-coupon bond paying $100. Its yield follows a simple curve
  around the central bank's policy rate: the short end moves with the rate, the long end with the
  rate's long-run anchor (neutral rate plus inflation target), plus a term premium. When an AI
  central bank moves, bonds reprice at once.
- A basis arbitrageur trades futures against the index fund when they drift apart, as index
  arbitrage desks do: it is how a crash in futures spreads to the cash market.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from .book import BUY, SELL

STEPS_PER_YEAR = 6000  # four quarters of 1,500 steps


class FuturesParams(BaseModel):
    underlying: str = "IDX"
    name: str = "IDX.F"
    expiry_every: int = 1500  # steps: one contract per quarter
    dividend_yield: float = 1.5  # %, earned by holding the index fund but not the future


class BondParams(BaseModel):
    name: str = "BOND2Y"
    years: float = 2.0
    short_weight: float = 0.7  # how much of its yield follows the policy rate (vs the long-run anchor)
    term_premium: float = 0.2  # % added to the yield


class PerpParams(BaseModel):
    """A perpetual future (crypto style): no expiry; every `funding_every` steps longs pay shorts
    (or the reverse) the perp's premium over spot, which pulls the perp back toward spot."""

    underlying: str = "COIN"
    name: str = "COIN.P"
    funding_every: int = 480  # steps (about every 8 minutes)
    cap_bps: float = 50.0  # the most one funding payment can be, in bps of the position


class BasisArbParams(BaseModel):
    threshold_bps: float = 15.0
    size: int = 3
    max_position: int = 60


class DerivativesCfg(BaseModel):
    futures: FuturesParams | None = None
    bonds: list[BondParams] = []
    basis_arb: BasisArbParams | None = None
    perps: list[PerpParams] = []
    perp_arb: BasisArbParams | None = None  # a desk trading each perp against its spot


class Derivatives:
    """Fair values of the derived books, and the futures' expiry and settlement."""

    def __init__(self, cfg: DerivativesCfg, ex, economy, econ_params, index_price: float | None):
        self.cfg, self.ex, self.economy = cfg, ex, economy
        self.ep = econ_params
        self.names = ([cfg.futures.name] if cfg.futures else []) + [b.name for b in cfg.bonds] + [p.name for p in cfg.perps]
        self.settlements: list[dict] = []
        self.fundings: list[dict] = []

    def rate(self) -> float:
        if self.economy is not None:
            return self.economy.i
        return self.ep.i0 if self.ep else 3.0

    def bond_yield(self, b: BondParams) -> float:
        anchor = (self.ep.r_star + self.ep.pi_target) if self.ep else 3.0
        return b.short_weight * self.rate() + (1 - b.short_weight) * anchor + b.term_premium * b.years ** 0.5

    def values(self, v: dict[str, float], t: int) -> dict[str, float]:
        out = {}
        f = self.cfg.futures
        if f:
            tau = (f.expiry_every - t % f.expiry_every) / STEPS_PER_YEAR
            out[f.name] = v[f.underlying] * math.exp((self.rate() - f.dividend_yield) / 100 * tau)
        for b in self.cfg.bonds:
            out[b.name] = 10_000 * math.exp(-self.bond_yield(b) / 100 * b.years)
        for p in self.cfg.perps:
            out[p.name] = v[p.underlying]
        return out

    def fair(self, name: str, spot: float) -> float:
        """A future's or perp's fair price given its underlying's price now."""
        f = self.cfg.futures
        if f and name == f.name:
            return self.values({f.underlying: spot}, self.ex.t)[name]
        return spot

    def fund(self) -> list[dict]:
        """Funding payments on the perps that are due this step."""
        ex, out = self.ex, []
        for p in self.cfg.perps:
            if ex.t == 0 or ex.t % p.funding_every:
                continue
            perp, spot = ex.mid(p.name), ex.mid(p.underlying)
            if not (perp and spot):
                continue
            rate = max(-p.cap_bps, min(p.cap_bps, (perp / spot - 1) * 1e4)) / 1e4
            longs = 0.0
            for acc in ex.accounts.values():
                q = acc.pos.get(p.name, 0)
                if q:
                    acc.cash -= q * perp * rate  # longs pay shorts when the perp trades rich
                    longs += max(q, 0) * perp * rate
            rec = {"t": ex.t, "perp": p.name, "rate_bps": round(rate * 1e4, 2), "paid_by_longs": round(longs, 1)}
            self.fundings.append(rec)
            out.append(rec)
        return out

    def expire(self, values: dict[str, float], zi) -> dict | None:
        """At a contract's expiry: cash-settle every position at the underlying's value, clear the
        book, and seed the next contract's book around its fair value."""
        f, ex = self.cfg.futures, self.ex
        if not f or ex.t == 0 or ex.t % f.expiry_every:
            return None
        rec = settle_future(ex, zi, f.name, values[f.underlying], values[f.name])
        self.settlements.append(rec)
        return rec


def settle_future(ex, zi, name: str, px: float, next_px: float) -> dict:
    """Expire a futures contract: cash-settle every position at px, clear the book, and seed the
    next contract's book around its fair value next_px."""
    book = ex.books[name]
    for oid in list(book.orders):
        book.cancel(oid)
    held = {}
    for owner, acc in ex.accounts.items():
        q = acc.pos.get(name, 0)
        if q:
            acc.cash += q * px
            acc.pos[name] = 0
            held[owner] = q
    ex.last_px[name] = px
    for z in zi:
        if z.asset == name:
            z.seed(next_px)
    return {"t": ex.t, "contract": name, "settle_price": round(px, 1), "positions": held}


class BasisArb:
    """Trades a future (or perp) against its underlying when the basis strays from fair: sells the
    rich leg and buys the cheap one, as index-arbitrage and crypto basis desks do."""

    def __init__(self, ex, deriv: Derivatives, p: BasisArbParams, underlying: str, name: str, owner: str):
        self.ex, self.d, self.p = ex, deriv, p
        self.underlying, self.name, self.owner = underlying, name, owner

    def step(self, values: dict, lagged: dict) -> None:
        ex, u, f = self.ex, self.underlying, self.name
        spot, fut = ex.mid(u), ex.mid(f)
        if not (spot and fut) or ex.halted(f) or ex.halted(u):
            return
        pos = ex.accounts[self.owner].pos.get(f, 0)
        # stay hedged first: the spot leg mirrors the derivative leg (after a future settles, the
        # spot leg is unwound)
        drift = ex.accounts[self.owner].pos.get(u, 0) + pos
        if drift:
            ex.market(self.owner, u, SELL if drift > 0 else BUY, min(abs(drift), self.p.size))
            return
        gap = (fut / self.d.fair(f, spot) - 1) * 1e4
        if gap > self.p.threshold_bps and pos > -self.p.max_position:  # derivative rich: sell it, buy spot
            ex.market(self.owner, f, SELL, self.p.size)
            ex.market(self.owner, u, BUY, self.p.size)
        elif gap < -self.p.threshold_bps and pos < self.p.max_position:  # derivative cheap
            ex.market(self.owner, f, BUY, self.p.size)
            ex.market(self.owner, u, SELL, self.p.size)


def bond_yield_from_price(price: float, years: float) -> float:
    return -math.log(price / 10_000) / years * 100 if price > 0 else float("nan")


def initial_prices(cfg: DerivativesCfg, econ_params, prices: dict[str, float]) -> dict[str, float]:
    """Fair values at the start, for the benchmarks, given the underlyings' starting prices."""
    return Derivatives(cfg, None, None, econ_params, None).values(prices, 0)

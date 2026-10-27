"""Options and dealer hedging: how an options market feeds back into the stock.

Retail investors buy (or write) short-dated call options from an options dealer, off-exchange. The
dealer keeps its book delta-neutral by trading the stock on the lit market. Black-Scholes deltas
with the stock's per-step volatility:
- dealer SHORT calls (retail buys them): short gamma. As the price rises the calls' delta rises and
  the dealer must buy more stock; as it falls, sell. Hedging chases the price: a "gamma squeeze".
- dealer LONG calls (retail writes them, e.g. covered calls): long gamma. Hedging sells rallies and
  buys dips, damping moves.
Calls are cash-settled at expiry. Prices are in cents, one contract is one lot of stock.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel

from .book import BUY, SELL
from .exchange import Exchange


class OptionsParams(BaseModel):
    asset: str = "A"
    flow: Literal["retail_buys_calls", "retail_writes_calls"] = "retail_buys_calls"
    rate: float = 0.03  # contracts traded per step
    otm_pct: float = 1.0  # strike this % above the spot at purchase
    expiry: int = 2000  # steps to expiry
    sigma: float = 1.6e-4  # per-step log volatility used for pricing and deltas
    hedge_every: int = 5
    max_hedge_order: int = 10  # lots per hedge trade


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(s: float, k: float, tau: float, sigma: float) -> tuple[float, float, float]:
    """Call price, delta and gamma (per cent of spot) with zero rates; tau in steps."""
    if tau <= 0:
        return max(s - k, 0.0), float(s > k), 0.0
    v = sigma * math.sqrt(tau)
    d1 = (math.log(s / k) + 0.5 * v * v) / v
    d2 = d1 - v
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return s * _ncdf(d1) - k * _ncdf(d2), _ncdf(d1), pdf / (s * v)


class OptionsDealer:
    owner = "options_dealer"
    client = "retail_options"

    def __init__(self, ex: Exchange, p: OptionsParams, rng: np.random.Generator) -> None:
        self.ex, self.p, self.rng = ex, p, rng
        self.sign = -1 if p.flow == "retail_buys_calls" else 1  # dealer's position per contract
        self.book: list[dict] = []  # open contracts: strike, expiry, qty (dealer's signed)
        self.hedge_lots = 0
        self.history: list[dict] = []  # per-epoch summary, filled by stats()

    def greeks(self) -> tuple[float, float]:
        s, t = self.ex.mid(self.p.asset), self.ex.t
        delta = gamma = 0.0
        for c in self.book:
            _, d, g = bs_call(s, c["k"], c["expiry"] - t, self.p.sigma)
            delta += c["qty"] * d
            gamma += c["qty"] * g
        return delta, gamma

    def step(self, values: dict, lagged: dict) -> None:
        ex, p = self.ex, self.p
        s = ex.mid(p.asset)
        for _ in range(self.rng.poisson(p.rate)):  # new contracts, premium paid in cash
            k = round(s * (1 + p.otm_pct / 100))
            prem, _, _ = bs_call(s, k, p.expiry, p.sigma)
            self.book.append({"k": k, "expiry": ex.t + p.expiry, "qty": self.sign})
            ex.accounts[self.owner].cash -= self.sign * prem
            ex.accounts[self.client].cash += self.sign * prem
        for c in [c for c in self.book if c["expiry"] <= ex.t]:  # cash settlement
            payoff = max(s - c["k"], 0.0)
            ex.accounts[self.owner].cash += c["qty"] * payoff
            ex.accounts[self.client].cash -= c["qty"] * payoff
            self.book.remove(c)
        if ex.t % p.hedge_every == 0:
            delta, _ = self.greeks()
            target = -round(delta)  # stock position that offsets the options' delta
            gap = target - ex.accounts[self.owner].pos[p.asset]
            if gap:
                self.hedge_lots += ex.market(self.owner, p.asset, BUY if gap > 0 else SELL,
                                             min(abs(gap), p.max_hedge_order))  # fmt: skip

    def stats(self) -> dict:
        delta, gamma = self.greeks()
        return {"open_contracts": len(self.book), "dealer_delta": round(delta, 1),
                "dealer_gamma_per_pct": round(gamma * self.ex.mid(self.p.asset) / 100, 2),
                "hedge_lots": self.hedge_lots}  # fmt: skip

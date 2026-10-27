"""A crypto-style liquidation engine: a ladder of leveraged longs, an insurance fund and
auto-deleveraging (ADL), as on perpetual-futures venues in the 10 Oct 2025 cascade.

Each long account opens with leverage drawn from [leverage_min, leverage_max] (capped by the
venue's leverage_cap), so their liquidation prices form a ladder below the market. Short accounts
take the other side. When an account's equity falls below its maintenance margin, the engine
takes over its position and sells it into the book in chunks. A liquidation that ends with
negative equity is made whole by the insurance fund. If the fund is empty and ADL is on, the next
liquidation is not sent to the book: the position is closed against the most profitable shorts at
the bankruptcy price (the price where the account's equity is zero). That stops the forced
selling, but the winners pay for it by losing their positions.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from .book import BUY, SELL
from .exchange import Exchange


class LiquidationParams(BaseModel):
    asset: str = "A"
    n_longs: int = 30
    long_lots: int = 10
    leverage_min: float = 5.0
    leverage_max: float = 50.0
    leverage_cap: float | None = None  # the venue's maximum leverage
    maintenance: float = 0.5  # maintenance margin as a share of the initial margin
    n_shorts: int = 10
    short_lots: int = 10
    short_leverage: float = 3.0
    chunk: int = 4  # lots the engine sells per step and per account in liquidation
    insurance_fund: float = 1e9  # price units; effectively unlimited by default
    adl: bool = False


class LiquidationEngine:
    def __init__(self, ex: Exchange, p: LiquidationParams, rng: np.random.Generator) -> None:
        self.ex, self.p = ex, p
        self.fund = p.insurance_fund
        self.fund_min = p.insurance_fund
        self.liquidating: set[str] = set()
        self._bankrupt: set[str] = set()
        self.events: list[dict] = []  # liquidations started and ADL closes
        self.liquidated_lots = self.adl_lots = 0
        self.insurance_paid = 0.0
        px = ex.mid(p.asset)
        cap = p.leverage_cap or float("inf")
        levs = rng.uniform(p.leverage_min, p.leverage_max, p.n_longs)
        self.accounts: dict[str, dict] = {}
        for i, lev in enumerate(levs):
            self._open(f"perp_long_{i:02d}", p.long_lots, min(float(lev), cap), px)
        for i in range(p.n_shorts):
            self._open(f"perp_short_{i:02d}", -p.short_lots, min(p.short_leverage, cap), px)

    def _open(self, owner: str, q: int, lev: float, px: float) -> None:
        acct = self.ex.accounts[owner]
        margin = abs(q) * px / lev
        acct.pos[self.p.asset] += q
        acct.cash += margin - q * px
        self.accounts[owner] = {"leverage": round(lev, 1), "margin": margin}

    def equity(self, owner: str, px: float) -> float:
        acct = self.ex.accounts[owner]
        return acct.cash + acct.pos[self.p.asset] * px

    def step(self, values: dict, lagged: dict) -> None:
        ex, p = self.ex, self.p
        px = ex.mid(p.asset)
        for owner, info in self.accounts.items():
            q = ex.accounts[owner].pos[p.asset]
            if q == 0:
                continue
            if owner not in self.liquidating:
                if self.equity(owner, px) >= p.maintenance * abs(q) * px / info["leverage"]:
                    continue
                self.liquidating.add(owner)
                self.events.append({"t": ex.t, "kind": "liquidation", "owner": owner,
                                    "leverage": info["leverage"], "position": q, "price": round(px, 1)})  # fmt: skip
            # ADL: once the insurance fund is used up, a bankrupt position is not sold into the book
            if p.adl and self.fund <= 0 and self.equity(owner, px) <= 0 and self._adl(owner, q):
                continue
            n = ex.market(owner, p.asset, SELL if q > 0 else BUY, min(p.chunk, abs(q)))
            self.liquidated_lots += n
            if ex.accounts[owner].pos[p.asset] == 0:
                self._settle(owner)
            elif (eq := self.equity(owner, ex.mid(p.asset))) < 0 and owner not in self._bankrupt:
                self._bankrupt.add(owner)  # the fund is drawn as soon as an account is bankrupt
                self.fund += eq
                self.insurance_paid -= eq
                ex.accounts[owner].cash -= eq
                self.fund_min = min(self.fund_min, self.fund)

    def _settle(self, owner: str) -> None:
        """A closed account with negative equity is made whole by the insurance fund."""
        self.liquidating.discard(owner)
        acct = self.ex.accounts[owner]
        if acct.cash < 0:
            self.fund += acct.cash
            self.insurance_paid -= acct.cash
            acct.cash = 0.0
            self.fund_min = min(self.fund_min, self.fund)

    def _adl(self, owner: str, q: int) -> bool:
        """Close a bankrupt long against the most profitable opposite positions at its bankruptcy
        price. Returns False if there is nobody to deleverage."""
        ex, a = self.ex, self.p.asset
        acct = ex.accounts[owner]
        bankrupt_px = max(1.0, -acct.cash / q)  # equity is zero here
        px = ex.mid(a)
        opp = [o for o in self.accounts if ex.accounts[o].pos[a] * q < 0]
        opp.sort(key=lambda o: -self.equity(o, px))  # most profitable first
        left = abs(q)
        for o in opp:
            take = min(left, abs(ex.accounts[o].pos[a]))
            if take:
                ex.internalise(owner, o, a, SELL if q > 0 else BUY, take, bankrupt_px)
                self.events.append({"t": ex.t, "kind": "adl", "owner": o, "qty": take,
                                    "price": round(bankrupt_px, 1)})  # fmt: skip
                self.adl_lots += take
                left -= take
            if not left:
                break
        if ex.accounts[owner].pos[a] == 0:
            self._settle(owner)
        return left < abs(q)

    def stats(self) -> dict:
        a = self.p.asset
        return {"liquidations": sum(e["kind"] == "liquidation" for e in self.events),
                "liquidated_lots": self.liquidated_lots, "adl_lots": self.adl_lots,
                "insurance_paid": round(self.insurance_paid, 1), "insurance_fund": round(self.fund, 1),
                "open_long_lots": sum(max(0, self.ex.accounts[o].pos[a]) for o in self.accounts)}  # fmt: skip

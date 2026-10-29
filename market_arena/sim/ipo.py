"""An IPO: a founder takes a private company public through an investment bank's bookbuild.

The company (a component of kind "private") has a hidden fair value like any stock, but its book
is closed until it lists. The process runs over three epochs:
- end of `found_epoch`: the founder files (company name, business, pitch, lots to sell, a reserve
  price); then the bank, after its due diligence, sets a price range.
- end of the next epoch (the bookbuild): AI investors read the prospectus, each with its own
  research desk's valuation, and may put in an order (lots at up to a price). Retail demand is a
  fixed number of lots at any price within the range. Then the bank sets the offer price and
  allocates the lots. It underwrites on a firm commitment: lots it cannot place, it keeps.
- the start of the epoch after: the stock lists. The bank's fee (gross spread) is taken from the
  proceeds. The book opens around the offer price and the crowd learns the true value over time,
  so the first-day move shows how far the offer was from the company's worth.

Everyone sees a noisy estimate of the true value at filing: the founder the most precise one, the
bank a little less, each investor less again, and independent across investors, as in Rock's (1986)
model of IPO underpricing. The estimates are drawn from the seed, so a run replays.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from .news import COMPANIES



class IPOParams(BaseModel):
    asset: str = "D"
    found_epoch: int = 3  # the founder files at the end of this epoch; the stock lists two epochs later
    shares: int = 200  # lots offered, unless the founder chooses (between half and double this)
    fee_pct: float = 7.0  # the bank's gross spread, % of proceeds
    founder_noise: float = 0.05  # sd of each party's valuation error (log)
    bank_noise: float = 0.08
    investor_noise: float = 0.15
    retail_lots: int = 40  # retail demand, at any price within the range
    max_order: int = 40  # lots an investor may ask for
    default_name: str = "Dynamo Drones"
    default_business: str = "a maker of autonomous drones for logistics and defence"


class IPO:
    def __init__(self, p: IPOParams, ex, fund, steps_per_epoch: int, seed: int) -> None:
        self.p, self.ex, self.fund = p, ex, fund
        self.spe = steps_per_epoch
        self.list_step = (p.found_epoch + 2) * steps_per_epoch
        self.rng = np.random.default_rng([seed, 41])
        self.status = "private"  # -> filed -> bookbuilding -> priced -> listed
        self.prospectus: dict | None = None
        self.range: tuple[float, float] | None = None
        self.orders: dict[str, dict] = {}  # investor -> {lots, max_price}
        self.priced: dict | None = None  # {price, allocations, bank_kept, ...}
        self.value_at_filing: float | None = None
        self._z: dict[str, float] = {}  # each party's standard-normal valuation error
        self.headlines: list[tuple[int, str]] = []  # (t, text), drained by the market onto the wire

    def _value(self) -> float:
        return self.fund.values()[self.p.asset]

    def estimate(self, who: str, noise: float) -> float:
        """A party's private estimate of the company's value at filing (drawn once, in order of
        first use: the founder's review, then every investor at filing, then the bank's review)."""
        if self.value_at_filing is None:  # the founder's valuation fixes the filing date's value
            self.value_at_filing = self._value()
        if who not in self._z:
            self._z[who] = float(self.rng.normal())
        return self.value_at_filing * float(np.exp(noise * self._z[who] - noise**2 / 2))

    def file(self, founder: str, bank: str, investors: list[str], name: str, business: str, pitch: str,
             shares: int, reserve: float) -> dict:  # fmt: skip
        if self.status != "private":
            raise ValueError("the company has already filed")
        shares = int(np.clip(shares, self.p.shares // 2, self.p.shares * 2))
        self.prospectus = {"company": name[:60], "ticker": self.p.asset, "business": business[:200],
                           "pitch": pitch[:600], "lots_offered": shares, "reserve_price": round(float(reserve), 1),
                           "founder": founder, "lead_underwriter": bank}  # fmt: skip
        self.status = "filed"
        COMPANIES[self.p.asset] = self.prospectus["company"]  # headlines and prompts use its name
        for who in sorted(investors):  # draw everyone's errors now, in a fixed order
            self.estimate(who, self.p.investor_noise)
        self.headlines.append((self.ex.t, f"{name} files for an IPO of {shares} lots on the exchange, with "
                                          f"{bank} as lead underwriter: {business[:120]}"))  # fmt: skip
        return self.prospectus

    def set_range(self, low: float, high: float, note: str = "") -> None:
        if self.status != "filed":
            raise ValueError("a range is set once, after filing")
        if not 0 < low <= high <= 1.5 * low:
            raise ValueError("need 0 < low <= high <= 1.5 x low")
        self.range = (round(float(low), 1), round(float(high), 1))
        self.status = "bookbuilding"
        co = self.prospectus["company"]
        self.headlines.append((self.ex.t, f"{co} IPO: price range set at {self.range[0]:.0f}-{self.range[1]:.0f} "
                                          f"cents a share; the book is open" + (f". {note[:160]}" if note else "")))  # fmt: skip

    def order(self, investor: str, lots: int, max_price: float) -> dict:
        if self.status != "bookbuilding":
            raise ValueError("no IPO book is open")
        lots = int(np.clip(lots, 0, self.p.max_order))
        if lots:
            self.orders[investor] = {"lots": lots, "max_price": round(float(max_price), 1)}
        else:
            self.orders.pop(investor, None)
        return {"ok": True, "order": self.orders.get(investor)}

    def demand(self) -> list[dict]:
        """The book: every order, largest limit first, with retail's (at the top of the range)."""
        rows = [{"investor": i, **o} for i, o in sorted(self.orders.items())]
        if self.p.retail_lots and self.range:
            rows.append({"investor": "retail", "lots": self.p.retail_lots, "max_price": self.range[1]})
        return sorted(rows, key=lambda r: (-r["max_price"], r["investor"]))

    def lots_at(self, price: float) -> int:
        return sum(r["lots"] for r in self.demand() if r["max_price"] >= price)

    def price(self, bank: str, price: float, allocations: dict[str, int], rationale: str = "") -> dict:
        """Set the offer price and allocations. Only orders with a limit at or above the price can
        be filled, each up to its size; whatever is not allocated, the bank keeps."""
        if self.status != "bookbuilding":
            raise ValueError("the book is not open")
        lo, hi = self.range
        if not 0.5 * lo <= price <= 1.5 * hi:
            raise ValueError(f"price must be within 0.5 x low ({0.5 * lo:.0f}) and 1.5 x high ({1.5 * hi:.0f})")
        book = {r["investor"]: r for r in self.demand()}
        alloc = {}
        for inv, q in allocations.items():
            q = int(q)
            if q <= 0:
                continue
            if inv not in book:
                raise ValueError(f"{inv} has no order in the book")
            if book[inv]["max_price"] < price:
                raise ValueError(f"{inv}'s limit {book[inv]['max_price']} is below the price")
            alloc[inv] = min(q, book[inv]["lots"])
        offered = self.prospectus["lots_offered"]
        if sum(alloc.values()) > offered:
            raise ValueError(f"allocated {sum(alloc.values())} lots; only {offered} are offered")
        kept = offered - sum(alloc.values())
        self.priced = {"price": round(float(price), 1), "allocations": alloc, "bank_kept": kept, "bank": bank,
                       "demand_at_price": self.lots_at(price), "covered": round(self.lots_at(price) / offered, 2),
                       "rationale": rationale[:600]}  # fmt: skip
        self.status = "priced"
        co = self.prospectus["company"]
        self.headlines.append((self.ex.t, f"{co} prices its IPO at {price:.0f} cents, "
                                          f"{'above' if price > hi else 'below' if price < lo else 'within'} the range; "
                                          f"book {self.priced['covered']:.1f}x covered at the price"))  # fmt: skip
        return self.priced

    def step(self, zi) -> dict | None:
        """At the listing step: settle the offering and open the book."""
        if self.ex.t != self.list_step or self.status != "priced":
            return None
        ex, a, pr = self.ex, self.p.asset, self.priced
        px, bank = pr["price"], pr["bank"]
        founder = self.prospectus["founder"]
        holders = {**pr["allocations"], **({bank: pr["bank_kept"]} if pr["bank_kept"] else {})}
        for who, q in holders.items():
            ex.accounts[who].pos[a] += q
            ex.accounts[who].cash -= q * px
        proceeds = px * self.prospectus["lots_offered"]
        fee = proceeds * self.p.fee_pct / 100
        ex.accounts[founder].cash += proceeds - fee
        ex.accounts[bank].cash += fee
        ex.halted_until[a] = ex.t
        ex.last_px[a] = px
        for z in zi:
            if z.asset == a:
                z.seed(px)
        self.status = "listed"
        pr.update(value_at_listing=round(self._value(), 1), fee=round(fee, 1), proceeds=round(proceeds, 1))
        self.headlines.append((ex.t, f"{self.prospectus['company']} ({a}) begins trading at {px:.0f} cents"))
        return pr

    def unlisted(self) -> bool:
        return self.status != "listed"

    def view(self, who: str | None = None) -> dict:
        """What a party can see: the prospectus, the range, the book's state, and its own estimate."""
        out = {"status": self.status, "prospectus": self.prospectus, "price_range": self.range,
               "lists_at_step": self.list_step, "bank_fee_pct": self.p.fee_pct}  # fmt: skip
        if self.priced:
            out["offer"] = {k: self.priced[k] for k in ("price", "covered")}
        if who and self.value_at_filing and who in self._z:
            out["your_research_valuation"] = round(self.estimate(who, self.p.investor_noise), 1)
            out["your_order"] = self.orders.get(who)
        return out


def ipo_first_day(hist, ipo: IPO, steps: int) -> dict | None:
    """The offer against the value and the market price after listing."""
    if not ipo.priced or ipo.status != "listed":
        return None
    a, t0, pr = ipo.p.asset, ipo.list_step, ipo.priced
    mid = hist.get(a, "mid")
    val = hist.get(a, "value")
    t1 = min(len(mid) - 1, t0 + steps - 1)
    return {"company": ipo.prospectus["company"], "lots_offered": ipo.prospectus["lots_offered"],
            "range": ipo.range, "offer": pr["price"], "value_at_filing": round(ipo.value_at_filing, 1),
            "value_at_listing": pr["value_at_listing"], "covered": pr["covered"],
            "underpricing_pct": round((pr["value_at_listing"] / pr["price"] - 1) * 100, 2),
            "first_epoch_return_pct": round((float(mid[t1]) / pr["price"] - 1) * 100, 2),
            "price_after_epoch": round(float(mid[t1]), 1), "value_after_epoch": round(float(val[t1]), 1),
            "money_left_on_table": round((float(mid[t1]) - pr["price"]) * ipo.prospectus["lots_offered"], 1),
            "bank_fee": pr["fee"], "bank_kept_lots": pr["bank_kept"], "allocations": pr["allocations"],
            "orders": ipo.demand(), "rationale": pr.get("rationale")}  # fmt: skip

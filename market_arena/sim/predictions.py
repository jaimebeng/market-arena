"""Prediction markets on the run's own events.

At the end of each quarter, binary contracts open on what will happen in the next one: will the
central bank cut, will the index fund close above today's level, will a leveraged account be
liquidated, will the regulator refer anyone, will inflation come in above a threshold. Each pays
UNIT cents per share if it happens. An LMSR market maker (Hanson's logarithmic market scoring
rule) always quotes a price, which is the market's probability. It opens at a simple model's
forecast; a scripted crowd keeps trading toward that model as the quarter unfolds; AI investors
bet at their reviews by stating a probability and a stake. Whether the AI traders improve on the
model is then a scored question (Brier score against what happened).
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel

UNIT = 1000.0  # cents a winning share pays ($10)
KINDS = ("rate_cut", "index_up", "liquidations", "referral", "inflation")


class PredictionParams(BaseModel):
    liquidity: float = 30.0  # LMSR b, in shares: higher = prices move less per bet
    contracts: list[str] = list(KINDS)
    max_bet: int = 20  # shares per agent per contract per review
    crowd_every: int = 50  # steps between the crowd's trades
    crowd_size: int = 2  # shares per crowd trade
    inflation_threshold: float = 2.5


class Contract:
    def __init__(self, cid: str, kind: str, question: str, quarter: int, opened_t: int, b: float, p0: float):
        self.id, self.kind, self.question, self.quarter, self.opened_t, self.b = cid, kind, question, quarter, opened_t, b
        self.reset(p0)
        self.p_after_ai: float | None = None
        self.outcome: bool | None = None
        self.pos: dict[str, list[float]] = {}  # owner -> [YES shares, NO shares]
        self.paid: dict[str, float] = {}  # owner -> cents paid in
        self.level: float | None = None

    def reset(self, p0: float) -> None:
        """Open at probability p0 (the model's forecast): the market maker's subsidy sets it there."""
        p0 = min(max(p0, 0.03), 0.97)
        self.q = [self.b * math.log(p0 / (1 - p0)), 0.0]  # shares sold of (YES, NO)
        self.p_model_open = p0

    def price(self) -> float:
        a, b = (x / self.b for x in self.q)
        m = max(a, b)
        return math.exp(a - m) / (math.exp(a - m) + math.exp(b - m))

    def _cost(self, q) -> float:
        a, b = (x / self.b for x in q)
        m = max(a, b)
        return self.b * (m + math.log(math.exp(a - m) + math.exp(b - m)))

    def buy(self, owner: str, yes: bool, shares: float) -> float:
        """Buy shares of YES or NO; returns the cost in cents."""
        q = list(self.q)
        q[0 if yes else 1] += shares
        cost = (self._cost(q) - self._cost(self.q)) * UNIT
        self.q = q
        pos = self.pos.setdefault(owner, [0.0, 0.0])
        pos[0 if yes else 1] += shares
        self.paid[owner] = self.paid.get(owner, 0.0) + cost
        return cost

    def buy_to(self, owner: str, belief: float, max_shares: float) -> tuple[bool, float, float] | None:
        """Trade toward a belief: buy YES if the price is below it, NO if above, until the price
        reaches the belief or the stake is spent. Returns (yes, shares, cost)."""
        p = self.price()
        belief = min(max(belief, 0.01), 0.99)
        if abs(belief - p) < 1e-6:
            return None
        yes = belief > p
        # shares that move the LMSR price exactly to the belief
        target = self.b * math.log(belief / (1 - belief))
        need = (target - (self.q[0] - self.q[1])) if yes else ((self.q[0] - self.q[1]) - target)
        shares = round(min(max(need, 0.0), max_shares), 3)
        if shares <= 0:
            return None
        return yes, shares, self.buy(owner, yes, shares)

    def settle(self, outcome: bool) -> dict[str, float]:
        """Resolve; returns each owner's payout in cents."""
        self.outcome = outcome
        return {o: (p[0] if outcome else p[1]) * UNIT for o, p in self.pos.items()}

    def card(self) -> dict:
        return {"id": self.id, "kind": self.kind, "question": self.question, "quarter": self.quarter,
                "p": round(self.price(), 3), "p_model_open": round(self.p_model_open, 3),
                "p_after_ai": None if self.p_after_ai is None else round(self.p_after_ai, 3),
                "outcome": self.outcome}  # fmt: skip


class PredictionMarket:
    """The contracts of a run, the model the crowd trades on, and settlement into the exchange's
    accounts (so prediction-market profits show up in each agent's equity)."""

    def __init__(self, p: PredictionParams, rng: np.random.Generator):
        self.p, self.rng = p, rng
        self.contracts: list[Contract] = []
        self.pending: dict[str, list[dict]] = {}  # agent -> bets made at this review, run in a fixed order

    def open(self) -> list[Contract]:
        return [c for c in self.contracts if c.outcome is None]

    # ---- the model the crowd trades on ----------------------------------------------------------
    def belief(self, c: Contract, arena) -> float:
        ex, econ, spe = arena.ex, arena.market.economy, arena.cfg.steps_per_epoch
        end = (c.quarter + 1) * spe
        if c.kind == "index_up":
            idx = arena.cfg.index["name"]
            mid = arena.hist.get(idx, "mid", max(0, ex.t - 300), ex.t)
            r = np.diff(np.log(mid[np.isfinite(mid)]))
            sd = (float(np.std(r)) if len(r) > 10 else 2e-4) * math.sqrt(max(end - ex.t, 1))
            z = math.log(ex.mid(idx) / c.level) / max(sd, 1e-6)
            return 0.5 * (1 + math.erf(z / math.sqrt(2)))
        if c.kind == "rate_cut":  # the Taylor rule's advice against the current rate
            return 1 / (1 + math.exp(-(econ.i - econ.taylor()) / 0.25))
        if c.kind == "inflation":  # next quarter's inflation: about this quarter's, give or take
            return 0.5 * (1 + math.erf((econ.pi - self.p.inflation_threshold) / 0.5 / math.sqrt(2)))
        if c.kind == "liquidations":
            perps = arena.market.perps
            n = sum(e["kind"] == "liquidation" for e in perps.events) if perps else 0
            if any(e["kind"] == "liquidation" and e["t"] >= c.quarter * spe for e in perps.events):
                return 0.99
            rate = (n + 0.5) / max(ex.t, spe)  # per step, with a small prior
            return 1 - math.exp(-rate * max(end - ex.t, 0))
        if c.kind == "referral":  # how often past reviews ended in a referral
            past = [any(f.get("severity") == "referral" for f in r["findings"]) for r in self._reg_reports(arena)]
            return (sum(past) + 1) / (len(past) + 2)
        return 0.5

    @staticmethod
    def _reg_reports(arena) -> list[dict]:
        reg = next((ag for ag in arena.agents if ag.role == "regulator"), None)
        return getattr(reg, "reports", []) if reg else []

    # ---- lifecycle ------------------------------------------------------------------------------
    def open_quarter(self, arena, quarter: int) -> list[Contract]:
        """Open the contracts on `quarter` (0-based): at the start of the run for the first one, then
        at each quarter's end, before the reviews, for the next."""
        new = []
        last = quarter == arena.cfg.n_epochs - 1  # no review or rate decision follows the last quarter
        idx = arena.cfg.index["name"] if arena.cfg.index else None
        has = {"rate_cut": arena.market.economy is not None, "inflation": arena.market.economy is not None,
               "index_up": idx is not None, "liquidations": arena.market.perps is not None,
               "referral": any(ag.role == "regulator" for ag in arena.agents)}  # fmt: skip
        for kind in self.p.contracts:
            if not has.get(kind) or (last and kind in ("rate_cut", "referral")):
                continue
            q = quarter + 1  # as people count quarters
            text = {
                "rate_cut": f"Will the central bank cut rates at the end of quarter {q}?",
                "index_up": f"Will the index fund close quarter {q} above ${arena.ex.mid(idx) / 100:.2f}?" if idx else "",
                "liquidations": f"Will any leveraged account be liquidated in quarter {q}?",
                "referral": f"Will the regulator refer anyone for misconduct after quarter {q}?",
                "inflation": f"Will inflation come in above {self.p.inflation_threshold}% for quarter {q}?",
            }[kind]  # fmt: skip
            c = Contract(f"q{q}_{kind}", kind, text, quarter, arena.ex.t, self.p.liquidity, 0.5)
            if kind == "index_up":
                c.level = arena.ex.mid(idx)
            c.reset(self.belief(c, arena))
            self.contracts.append(c)
            new.append(c)
        return new

    def crowd_step(self, arena) -> None:
        for c in self.open():
            if c.quarter * arena.cfg.steps_per_epoch > arena.ex.t:
                continue  # not trading yet: its quarter has not started
            belief = self.belief(c, arena) + self.rng.normal(0, 0.03)
            if abs(belief - c.price()) > 0.02:
                c.buy_to("pm_crowd", belief, self.p.crowd_size)

    def run_bets(self, arena) -> list[dict]:
        """Execute the AI bets made at a review, in agent order (reviews finish in any order, and
        each bet moves the price the next one gets, so a replay needs a fixed order)."""
        done = []
        for agent in sorted(self.pending):
            for bet in self.pending[agent]:
                c = next((x for x in self.open() if x.id == bet["contract"]), None)
                if c is None:
                    continue
                r = c.buy_to(agent, bet["probability"], min(bet["shares"], self.p.max_bet))
                if r:
                    yes, shares, cost = r
                    arena.ex.accounts[agent].cash -= cost
                    done.append({"agent": agent, "contract": c.id, "probability": bet["probability"],
                                 "side": "YES" if yes else "NO", "shares": shares, "cost": round(cost, 1),
                                 "price_after": round(c.price(), 3)})  # fmt: skip
        self.pending = {}
        for c in self.open():
            if c.p_after_ai is None and c.opened_t <= arena.ex.t:
                c.p_after_ai = c.price()
        return done

    def resolve(self, arena, kinds: tuple[str, ...], quarter: int, outcome_of) -> list[dict]:
        out = []
        for c in self.open():
            if c.kind in kinds and c.quarter == quarter:
                outcome = bool(outcome_of(c))
                for owner, cents in c.settle(outcome).items():
                    if owner in arena.ex.accounts:
                        arena.ex.accounts[owner].cash += cents
                out.append(c.card())
        return out

    def prices(self) -> dict[str, float]:
        return {c.id: round(c.price(), 3) for c in self.open()}

    def tool_view(self, agent: str) -> list[dict]:
        """What an AI investor sees: open contracts, prices, its own holdings."""
        return [{"contract": c.id, "question": c.question, "probability_now": round(c.price(), 3),
                 "your_yes_shares": round(c.pos.get(agent, [0, 0])[0], 2),
                 "your_no_shares": round(c.pos.get(agent, [0, 0])[1], 2),
                 "pays_cents_per_share": UNIT} for c in self.open()]  # fmt: skip

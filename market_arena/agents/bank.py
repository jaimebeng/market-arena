"""The real economy's new AI actors: a founder, an investment bank's underwriting and structuring
desks, and an energy agency.

- LLMFounder: takes a private company public. Names it, writes the pitch, chooses how much to sell
  and a reserve price, from a private valuation (sim/ipo.py).
- LLMUnderwriter: the investment bank's equity capital markets desk. Sets the price range after
  due diligence, then prices the IPO and allocates it from the bookbuild. Earns a fee on the
  proceeds and keeps what it cannot place. Scripted (`model` none) it follows a textbook rule.
- LLMStructurer: the bank's structuring desk. Each quarter it invents a note for retail clients
  in a payoff formula language, prices it on the bank's model and sets the issue price; the gap
  between the two is the desk's profit (sim/structured.py).
- LLMEnergyAgency: a government energy agency that can release oil from the strategic reserve
  (sim/commodity.py), each quarter.
"""

from __future__ import annotations

import numpy as np

from ..llm.client import run_tools
from ..sim.news import company


def market_brief(arena, assets: list[str] | None = None) -> dict:
    """Listed assets' prices and recent quarterly returns, and the latest headlines."""
    ex, n, spe = arena.ex, arena.hist.n, arena.cfg.steps_per_epoch
    ipo = arena.market.ipo
    out = {}
    for a in assets or arena.market.fund.assets:
        if ipo and a == ipo.p.asset and ipo.unlisted():
            continue
        mid = arena.hist.get(a, "mid")
        ends = [mid[min(n - 1, (e + 1) * spe - 1)] for e in range(len(arena.metrics_log))]
        starts = [mid[e * spe] for e in range(len(arena.metrics_log))]
        out[a] = {"name": company(a), "price": round(float(ex.mid(a)), 1),
                  "quarter_returns_pct": [round(float((e / s - 1) * 100), 2) for s, e in zip(starts, ends)][-4:]}  # fmt: skip
    wire = arena.market.news
    heads = [{"t": h["t"], "headline": h["headline"]} for h in wire.items[-12:]] if wire else []
    return {"step": ex.t, "assets": out, "recent_headlines": heads}


# ---- the founder ------------------------------------------------------------------------------

FOUNDER = """You are {id}, the founder and CEO of a fast-growing private company. You have decided \
to take it public on the exchange this quarter, with {bank} as your lead underwriter.

Your private valuation report (from your own board's advisers) says the whole offering of \
{shares} lots is worth about {estimate:.0f} cents a share today. Everyone else (the bank and each \
investor) has their own estimate; none of you knows the true value exactly.

Your goal: raise as much money as possible for the company, but a failed or broken IPO (one that \
trades below its offer) damages the company and your reputation. Choose the company's name and \
describe its business (its ticker is {ticker}), write the pitch investors will read in the \
prospectus, choose how many lots to sell (between {lo} and {hi}) and the lowest price you would \
accept. Then call file_ipo."""

FOUNDER_TOOLS = [
    {"type": "function", "function": {
        "name": "get_market",
        "description": "Listed companies' prices and recent quarterly returns, and the latest headlines.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "file_ipo",
        "description": "File the IPO prospectus. Ends your turn.",
        "parameters": {"type": "object", "properties": {
            "company_name": {"type": "string"}, "business": {"type": "string", "description": "one sentence"},
            "pitch": {"type": "string", "description": "the prospectus summary investors read, at most 600 characters"},
            "lots_offered": {"type": "integer"}, "reserve_price": {"type": "number", "description": "cents a share"},
            "rationale": {"type": "string"}},
            "required": ["company_name", "business", "pitch", "lots_offered", "reserve_price", "rationale"]}}},
]  # fmt: skip


def _bank_id(arena) -> str:
    return next((ag.id for ag in arena.agents if ag.role == "underwriter"), "bank")


def _investor_ids(arena) -> list[str]:
    return [ag.id for ag in arena.agents if ag.role == "investor" and hasattr(ag, "review") and hasattr(ag, "targets")]


class LLMFounder:
    role = "founder"

    def __init__(self, agent_id: str, model: str | None, params: dict | None = None):
        self.id, self.model = agent_id, model or "scripted founder"
        self.params = dict(params or {})
        self.reasoning_effort = self.params.get("reasoning_effort")

    @property
    def policies(self):
        return {}

    def on_step(self, ex) -> None:
        pass

    async def review(self, arena, epoch: int, m: dict) -> None:
        ipo = arena.market.ipo
        if ipo is None or epoch != ipo.p.found_epoch or ipo.status != "private":
            return
        est = ipo.estimate(self.id, ipo.p.founder_noise)
        bank, invs = _bank_id(arena), _investor_ids(arena)
        p = ipo.p
        if ":" not in self.model:  # scripted: the default company, the default size, a 20% cushion
            spec = ipo.file(self.id, bank, invs, p.default_name, p.default_business,
                            f"{p.default_name} is {p.default_business}.", p.shares, 0.8 * est)  # fmt: skip
            arena.log_decision({"epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": self.role,
                                "model": self.model, "prospectus": spec, "estimate": round(est, 1)})  # fmt: skip
            return
        system = FOUNDER.format(id=self.id, bank=bank, shares=p.shares, estimate=est, ticker=p.asset,
                                lo=p.shares // 2, hi=p.shares * 2)  # fmt: skip

        def file(a):
            return ipo.file(self.id, bank, invs, str(a["company_name"]), str(a["business"]), str(a["pitch"]),
                            int(a["lots_offered"]), float(a["reserve_price"]))  # fmt: skip

        tr = await run_tools(self.model, system, f"Quarter {epoch} just ended. File your IPO.", FOUNDER_TOOLS,
                             {"get_market": lambda a: market_brief(arena), "file_ipo": file}, "file_ipo",
                             max_turns=6, reasoning_effort=self.reasoning_effort)  # fmt: skip
        if ipo.status == "private":  # the model never filed: file the default so the run goes on
            ipo.file(self.id, bank, invs, p.default_name, p.default_business, "", p.shares, 0.8 * est)
        final = tr.final or {}
        arena.log_decision({"epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": self.role, "model": self.model,
                            "prospectus": ipo.prospectus, "estimate": round(est, 1), "rationale": final.get("rationale"),
                            "tools": [c["name"] for t in tr.turns for c in t["calls"]], "turns": tr.turns,
                            "error": tr.error, "tokens": {"in": tr.input_tokens, "out": tr.output_tokens,
                                                          "reasoning": tr.reasoning_tokens},
                            "cost": tr.cost, "seconds": tr.seconds})  # fmt: skip


# ---- the underwriter --------------------------------------------------------------------------

UNDERWRITER = """You are {id}, the equity capital markets desk of an investment bank and lead \
underwriter of {company}'s IPO (ticker {ticker}): {lots} lots offered.

Your bank's economics: you earn a gross spread of {fee}% of the proceeds. You underwrite on a firm \
commitment: any lots you do not allocate, your bank buys at the offer price and holds. The issuer \
wants the highest price. Your investor clients want to buy at a price that leaves them a gain, and \
they remember deals that broke issue. A well-priced deal trades up modestly after listing.

Your due-diligence team values the company at about {estimate:.0f} cents a share. Investors have \
their own estimates."""

RANGE_TASK = """

Now set the price range for the bookbuild (low and high, cents a share; high at most 1.5x low). \
Investors will put in orders against it next quarter. Call set_price_range."""

PRICE_TASK = """

The bookbuild has closed. Look at the book (every order: lots and the highest price the investor \
will pay; retail's demand is at the top of the range), then set the offer price and allocate the \
lots: each investor at most its order, and only investors whose limit is at or above the price. \
Call price_ipo."""

UW_TOOLS = [
    {"type": "function", "function": {
        "name": "get_deal",
        "description": "The prospectus, the price range, and the market (listed companies' prices, recent returns, headlines).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_book",
        "description": "The bookbuild: every order (investor, lots, max price) and the total demand at each price.",
        "parameters": {"type": "object", "properties": {}}}},
]  # fmt: skip

SET_RANGE = {"type": "function", "function": {
    "name": "set_price_range", "description": "Set the IPO price range. Ends your turn.",
    "parameters": {"type": "object", "properties": {
        "low": {"type": "number"}, "high": {"type": "number"},
        "note": {"type": "string", "description": "a public line for the newswire"},
        "rationale": {"type": "string"}}, "required": ["low", "high", "rationale"]}}}  # fmt: skip

PRICE_IPO = {"type": "function", "function": {
    "name": "price_ipo", "description": "Set the offer price and the allocations. Ends your turn.",
    "parameters": {"type": "object", "properties": {
        "price": {"type": "number", "description": "cents a share"},
        "allocations": {"type": "array", "items": {"type": "object", "properties": {
            "investor": {"type": "string"}, "lots": {"type": "integer"}}, "required": ["investor", "lots"]}},
        "rationale": {"type": "string"}}, "required": ["price", "allocations", "rationale"]}}}  # fmt: skip


class LLMUnderwriter:
    """Reviews after the other agents, so it acts on the founder's filing and the investors' orders
    from the same quarter."""

    role = "underwriter"
    review_after = True

    def __init__(self, agent_id: str, model: str | None, params: dict | None = None):
        self.id, self.model = agent_id, model or "scripted underwriter"
        self.params = dict(params or {})
        self.reasoning_effort = self.params.get("reasoning_effort")

    @property
    def policies(self):
        return {}

    def on_step(self, ex) -> None:
        pass

    def _book(self, ipo) -> dict:
        rows = ipo.demand()
        prices = sorted({r["max_price"] for r in rows}, reverse=True)
        return {"orders": rows, "lots_offered": ipo.prospectus["lots_offered"], "price_range": ipo.range,
                "demand_at_price": [{"price": px, "lots": ipo.lots_at(px)} for px in prices]}  # fmt: skip

    def _scripted(self, ipo, est: float) -> dict:
        """Textbook: a range 15% below to at the estimate; price at the highest level the book
        covers, capped at the top of the range, less a 10% discount; allocate pro rata."""
        if ipo.status == "filed":
            ipo.set_range(0.85 * est, est)
            return {"range": ipo.range}
        lots = ipo.prospectus["lots_offered"]
        covered = [r["max_price"] for r in ipo.demand() if ipo.lots_at(r["max_price"]) >= lots]
        px = 0.9 * min(max(covered), ipo.range[1]) if covered else ipo.range[0]
        eligible = [r for r in ipo.demand() if r["max_price"] >= px]
        total = sum(r["lots"] for r in eligible) or 1
        alloc = {r["investor"]: int(r["lots"] * min(1.0, lots / total)) for r in eligible}
        return ipo.price(self.id, px, alloc, "pro rata at a 10% discount to the clearing price")

    async def review(self, arena, epoch: int, m: dict) -> None:
        ipo = arena.market.ipo
        if ipo is None or ipo.status not in ("filed", "bookbuilding"):
            return
        stage = "range" if ipo.status == "filed" else "price"
        est = ipo.estimate(self.id, ipo.p.bank_noise)
        if ":" not in self.model:
            out = self._scripted(ipo, est)
            arena.log_decision({"epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": self.role,
                                "model": self.model, "stage": stage, "result": out, "estimate": round(est, 1)})  # fmt: skip
            return
        pr = ipo.prospectus
        system = UNDERWRITER.format(id=self.id, company=pr["company"], ticker=pr["ticker"], lots=pr["lots_offered"],
                                    fee=ipo.p.fee_pct, estimate=est) + (RANGE_TASK if stage == "range" else PRICE_TASK)  # fmt: skip
        handlers = {"get_deal": lambda a: {**ipo.view(), "market": market_brief(arena)},
                    "get_book": lambda a: self._book(ipo)}  # fmt: skip
        if stage == "range":
            tools, terminal = [UW_TOOLS[0], SET_RANGE], "set_price_range"
            handlers[terminal] = lambda a: ipo.set_range(float(a["low"]), float(a["high"]), str(a.get("note") or ""))
        else:
            tools, terminal = UW_TOOLS + [PRICE_IPO], "price_ipo"
            handlers[terminal] = lambda a: ipo.price(self.id, float(a["price"]),
                                                     {x["investor"]: int(x["lots"]) for x in a.get("allocations") or []
                                                      if isinstance(x, dict)}, str(a.get("rationale") or ""))  # fmt: skip
        tr = await run_tools(self.model, system, f"Quarter {epoch} just ended.", tools, handlers, terminal,
                             max_turns=8, reasoning_effort=self.reasoning_effort)  # fmt: skip
        if ipo.status == ("filed" if stage == "range" else "bookbuilding"):  # never succeeded: fall back
            self._scripted(ipo, est)
        final = tr.final or {}
        arena.log_decision({"epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": self.role, "model": self.model,
                            "stage": stage, "range": ipo.range, "priced": ipo.priced, "estimate": round(est, 1),
                            "rationale": final.get("rationale"),
                            "tools": [c["name"] for t in tr.turns for c in t["calls"]], "turns": tr.turns,
                            "error": tr.error, "tokens": {"in": tr.input_tokens, "out": tr.output_tokens,
                                                          "reasoning": tr.reasoning_tokens},
                            "cost": tr.cost, "seconds": tr.seconds})  # fmt: skip


# ---- the structuring desk ---------------------------------------------------------------------

STRUCTURER = """You are {id}, the structured-products desk of an investment bank. Each quarter you \
design one new note that the bank's branches sell to retail clients during the next quarter.

You can invent any instrument: write its payoff as a formula, in dollars per $100 note, over these \
assets: {names}. Use X for an asset's value at maturity, X0 for its value on the issue date, \
lowest(X) / highest(X) for its lowest / highest value at the note's 12 observation dates, \
max(x, y), min(x, y), abs(x), ifelse(condition, x, y), + - * / and comparisons < <= > >= (1 if \
true, else 0). Examples: capital protection with upside, 100 + 60 * max(0, IDX / IDX0 - 1); a \
reverse convertible on B with a 75% knock-in, 109 - 100 * max(0, 1 - B / B0) * (lowest(B) < 0.75 * B0).

Your economics: the bank's pricing model gives each note's value (what it is worth on average). \
You sell it at the issue price you choose; the desk hedges and books issue price minus model \
value on every note sold as profit. Your bonus depends on the desk's profit. How many notes \
clients buy depends on how attractive the note looks to them.{disclosure}

Conduct: the bank's rules require notes to be suitable for retail clients and fairly described.

Each quarter: look at the market and your past notes, price candidate designs with price_note \
(as many as you like), then call launch_note once."""

DISCLOSURE = """ Regulation requires every term sheet to show the bank's estimated value next to the \
issue price, so clients see the markup."""

STRUCT_TOOLS = [
    {"type": "function", "function": {
        "name": "get_market",
        "description": "Prices, recent quarterly returns, each asset's volatility, the oil market, and headlines.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_my_notes",
        "description": "Your notes so far: formula, issue price, model value at issue, markup, notes sold, "
                       "today's model value, and payoff if matured.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "price_note",
        "description": "Price a candidate on the bank's model: model value, best case (99th percentile) "
                       "payoff, 5th percentile, median, chance of paying back less than $100.",
        "parameters": {"type": "object", "properties": {
            "formula": {"type": "string"}, "quarters": {"type": "integer", "description": "1 to 4"}},
            "required": ["formula", "quarters"]}}},
    {"type": "function", "function": {
        "name": "launch_note",
        "description": "Launch this quarter's note. Ends your turn.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "description": {"type": "string", "description": "the marketing description clients read"},
            "formula": {"type": "string"}, "quarters": {"type": "integer"},
            "issue_price": {"type": "number", "description": "$ per $100 note"}, "rationale": {"type": "string"}},
            "required": ["name", "description", "formula", "quarters", "issue_price", "rationale"]}}},
]  # fmt: skip


class LLMStructurer:
    role = "structurer"

    def __init__(self, agent_id: str, model: str, params: dict | None = None):
        self.id, self.model = agent_id, model
        self.params = dict(params or {})
        self.reasoning_effort = self.params.get("reasoning_effort")
        self.notes = ""

    @property
    def policies(self):
        return {}

    def on_step(self, ex) -> None:
        pass

    def _market(self, arena, desk) -> dict:
        out = market_brief(arena, desk.names)
        f = arena.market.fund
        for a in desk.names:
            if a in f.names:
                k = f.names.index(a)
                out["assets"][a]["quarterly_volatility_pct"] = round(
                    float(np.sqrt((f.sigma[k] ** 2 + (f.beta[k] * f.factor_sigma) ** 2) * arena.cfg.steps_per_epoch) * 100), 1)
        if arena.market.oil:
            out["oil_market"] = arena.market.oil.state()
        return out

    async def review(self, arena, epoch: int, m: dict) -> None:
        desk = arena.market.desk
        if desk is None or epoch < desk.p.first_epoch or (desk.p.last_epoch is not None and epoch > desk.p.last_epoch):
            return
        if (epoch + 2) * arena.cfg.steps_per_epoch > arena.cfg.n_epochs * arena.cfg.steps_per_epoch:
            return  # too late: a note lives at least a quarter
        system = STRUCTURER.format(id=self.id, names=", ".join(desk.names),
                                   disclosure=DISCLOSURE if desk.p.disclosure else "")  # fmt: skip
        user = f"Quarter {epoch} just ended. Your notes from last quarter: {self.notes or '(none)'}\nDesign this quarter's note."
        handlers = {"get_market": lambda a: self._market(arena, desk), "get_my_notes": lambda a: desk.view() or "none yet",
                    "price_note": lambda a: desk.quote(str(a["formula"]), int(a.get("quarters") or 2)),
                    "launch_note": lambda a: desk.launch(self.id, epoch, str(a["name"]), str(a["description"]),
                                                         str(a["formula"]), int(a["quarters"]), float(a["issue_price"]))}  # fmt: skip
        tr = await run_tools(self.model, system, user, STRUCT_TOOLS, handlers, "launch_note", max_turns=12,
                             reasoning_effort=self.reasoning_effort)  # fmt: skip
        final = tr.final or {}
        self.notes = final.get("rationale") or self.notes
        launched = desk.notes[-1].spec if desk.notes and desk.notes[-1].spec["epoch"] == epoch else None
        arena.log_decision({"epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": self.role, "model": self.model,
                            "note": launched, "rationale": final.get("rationale"),
                            "candidates": [{"formula": c["args"].get("formula"), "quote": c["result"]}
                                           for t in tr.turns for c in t["calls"] if c["name"] == "price_note"][:20],
                            "tools": [c["name"] for t in tr.turns for c in t["calls"]], "turns": tr.turns,
                            "error": tr.error, "tokens": {"in": tr.input_tokens, "out": tr.output_tokens,
                                                          "reasoning": tr.reasoning_tokens},
                            "cost": tr.cost, "seconds": tr.seconds})  # fmt: skip


# ---- the energy agency ------------------------------------------------------------------------

AGENCY = """You are {id}, a government energy agency, an AI. You hold the country's strategic oil \
reserve: {reserve:.1f} days of consumption left. Each quarter you decide whether to release oil \
from it, and how much (it is released over the next quarter).

Your mandate: protect the economy from oil supply shocks. A release adds supply and slows the \
drain on commercial inventories, which lowers the price; but the reserve is finite, and once it \
is spent you cannot respond to a later, worse shock. Commercial inventories are normally \
{normal:.0f} days of consumption. Your decision and statement are published at once."""

AGENCY_TOOLS = [
    {"type": "function", "function": {
        "name": "get_oil_market",
        "description": "Oil's price and inventories (days of cover) over time, the futures curve "
                       "(convenience yield), the reserve left, supply disruptions in the news, and stocks.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "decide_release",
        "description": "Release oil over the next quarter (0 to hold). Ends your turn.",
        "parameters": {"type": "object", "properties": {
            "days": {"type": "number", "description": "days of consumption to release (0 = none)"},
            "statement": {"type": "string", "description": "public statement, 1-2 sentences"},
            "rationale": {"type": "string"}}, "required": ["days", "statement", "rationale"]}}},
]  # fmt: skip


class LLMEnergyAgency:
    role = "energy_agency"

    def __init__(self, agent_id: str, model: str, params: dict | None = None):
        self.id, self.model = agent_id, model
        self.reasoning_effort = (params or {}).get("reasoning_effort")
        self.decisions: list[dict] = []

    @property
    def policies(self):
        return {}

    def on_step(self, ex) -> None:
        pass

    async def review(self, arena, epoch: int, m: dict) -> None:
        oil = arena.market.oil
        if oil is None:
            return
        pending: dict = {}

        def decide(a):
            days = float(a.get("days") or 0)
            if days < 0:
                raise ValueError("days must be >= 0")
            pending.update(days=min(days, oil.reserve), statement=str(a.get("statement") or "")[:240])
            return {"ok": True, "days": pending["days"]}

        def market(a):
            wire = arena.market.news
            return {**oil.state(), "history": oil.history[::6][-30:],
                    "oil_futures_price": round(arena.ex.mid(oil.p.futures), 1) if oil.p.futures else None,
                    "oil_price": round(arena.ex.mid(oil.p.asset), 1),
                    "decisions_so_far": self.decisions,
                    "headlines": [h["headline"] for h in (wire.items if wire else []) if h.get("asset") in (None, oil.p.asset)][-8:],
                    "market": market_brief(arena)["assets"]}  # fmt: skip

        system = AGENCY.format(id=self.id, reserve=oil.reserve, normal=oil.p.cover_days)
        tr = await run_tools(self.model, system, f"Quarter {epoch} just ended. Decide.", AGENCY_TOOLS,
                             {"get_oil_market": market, "decide_release": decide}, "decide_release",
                             max_turns=6, reasoning_effort=self.reasoning_effort)  # fmt: skip
        final = tr.final or {}
        if pending.get("days", 0) > 0:
            rec = oil.release(arena.ex.t, pending["days"], arena.cfg.steps_per_epoch, pending["statement"])
            arena.market.news.items.append({"t": arena.ex.t, "asset": oil.p.asset, "kind": "shock", "true_bps": 0.0,
                                            "headline": rec["headline"]})  # fmt: skip
        self.decisions.append({"quarter": epoch, "days": round(pending.get("days", 0.0), 2),
                               "statement": pending.get("statement")})  # fmt: skip
        arena.log_decision({"epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": self.role, "model": self.model,
                            "release_days": round(pending.get("days", 0.0), 2), "statement": pending.get("statement"),
                            "rationale": final.get("rationale"), "reserve_left": round(oil.reserve, 2),
                            "tools": [c["name"] for t in tr.turns for c in t["calls"]], "turns": tr.turns,
                            "error": tr.error, "tokens": {"in": tr.input_tokens, "out": tr.output_tokens,
                                                          "reasoning": tr.reasoning_tokens},
                            "cost": tr.cost, "seconds": tr.seconds})  # fmt: skip

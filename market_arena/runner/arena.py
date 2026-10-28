"""The arena: builds the market from a config, runs epochs, calls agent reviews, records."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from ..agents.maker import Maker, MakerPolicy
from ..agents.reporter import MarketReporter
from ..sim.predictions import PredictionMarket
from ..sim.derivatives import BasisArb, Derivatives, initial_prices
from ..analysis.metrics import agent_metrics, class_metrics, drawdown, market_metrics
from ..analysis.stylized import stylized_facts
from ..agents.taker import StrategyTaker
from ..bench.game import GameParams, collusion_index, solve_nash, solve_pareto
from ..bench.glft import Calibration, calibrate, glft_policy, glft_quotes
from ..bench.signals import TEXTBOOK
from ..llm.client import CURRENT_AGENT
from ..sim.background import IndexFlow, InformedTrader, ZeroIntelligenceFlow
from ..sim.book import BUY
from ..sim.exchange import Exchange
from ..sim.fundamentals import Fundamentals
from ..sim.history import MarketHistory
from ..sim.economy import Economy
from ..sim.news import NewsWire, company, news_response
from ..sim.options import OptionsDealer
from ..sim.perps import LiquidationEngine
from ..sim.storyline import draw_storyline
from ..sim.participants import (CAMPAIGN_POSTS, IndexFund, InstitutionalFlow, LatencyArb, MarginDesk, RetailFlow,
                                Router, stream)
from .config import ArenaConfig

GENESIS = "0" * 64  # prev_hash of a run's first decision


def record_hash(rec: dict) -> str:
    """sha256 of a decision record (without its own hash), as canonical JSON."""
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


BACKGROUND = ("noise", "informed", "index_flow")
# investor classes whose trading costs the who-pays ledger reports
CLASSES = BACKGROUND + ("retail", "institutional", "fund_liquidation", "index_fund", "hft",
                        "options_dealer")


class Market:
    """Fundamentals + exchange + scripted background flow (+ the optional investor population).

    `calibration` builds the market used to fit the benchmarks: the investor population trades in
    it, but one-off shocks (a fire sale, leveraged accounts) do not."""

    def __init__(self, cfg: ArenaConfig, rng: np.random.Generator, seed: int | None = None,
                 calibration: bool = False) -> None:  # fmt: skip
        comps = {n: c.model_dump() for n, c in cfg.components.items()}
        self.fund = Fundamentals(comps, cfg.factor_sigma, rng, cfg.index, cfg.jump_rate, cfg.jump_bps)
        self.aliases = {x: stock for stock, xs in cfg.listings.items() for x in xs}  # listing -> stock
        dcfg = cfg.derivatives
        self.assets = self.fund.assets + list(self.aliases) + (
            ([dcfg.futures.name] if dcfg.futures else []) + [b.name for b in dcfg.bonds] + [p.name for p in dcfg.perps]
            if dcfg else [])  # fmt: skip
        self.ex = Exchange(self.assets, cfg.rules)
        # futures and bonds: books priced off the index fund and the policy rate (economy set below)
        self.deriv = Derivatives(dcfg, self.ex, None, cfg.economy, None) if dcfg else None
        v0 = self.values()
        self.zi = []
        for a in self.assets:
            z = ZeroIntelligenceFlow(self.ex, a, cfg.zi, rng)
            z.seed(v0[a])
            self.ex.last_px[a] = v0[a]
            self.zi.append(z)
        self.informed = InformedTrader(self.ex, cfg.informed, rng)
        self._values: deque = deque(maxlen=cfg.zi.anchor_lag + 1)
        self.index_flow = (
            IndexFlow(self.ex, cfg.index["name"], cfg.index_flow, rng)
            if cfg.index and cfg.index_flow
            else None
        )
        self.news = NewsWire(self.fund, cfg.news, stream(cfg.seed if seed is None else seed, 5)) if cfg.news else None
        self.economy = Economy(self.fund, cfg.economy, stream(cfg.seed if seed is None else seed, 7)) if cfg.economy else None
        if self.deriv:
            self.deriv.economy = self.economy
        self.router = Router(self.ex, {a: [a] + cfg.listings.get(a, []) for a in self.fund.assets})
        self.extra: list = []  # optional participants, stepped after the original flow
        self.retail = self.institutional = self.margin = self.options = self.perps = None
        self.shocks: dict[int, list] = {}  # step -> scheduled shocks
        for s in cfg.shocks if not calibration else []:
            self.shocks.setdefault(s.at_step, []).append(s)
        self.activity = 1.0  # share of scripted flow active this step (thinned overnight)
        self._thin = stream(cfg.seed if seed is None else seed, 8)
        pop, seed = cfg.population, cfg.seed if seed is None else seed
        if pop:
            if pop.retail:
                self.retail = RetailFlow(self.ex, self.router, pop.retail, stream(seed, 1))
                self.extra.append(self.retail)
            fire = None if calibration else pop.fire_sale
            if pop.institutional or fire:
                self.institutional = InstitutionalFlow(self.ex, self.router, pop.institutional, fire,
                                                       stream(seed, 2))  # fmt: skip
                self.extra.append(self.institutional)
            if pop.index_fund:
                self.extra.append(IndexFund(self.ex, self.router, pop.index_fund, stream(seed, 3)))
            if pop.latency_arb:
                self.extra.append(LatencyArb(self.ex, self.router, pop.latency_arb, stream(seed, 4)))
            if pop.leveraged and not calibration:
                self.margin = MarginDesk(self.ex, pop.leveraged)
                self.extra.append(self.margin)
            if pop.options and not calibration:
                self.options = OptionsDealer(self.ex, pop.options, stream(seed, 6))
                self.extra.append(self.options)
            if pop.liquidations and not calibration:
                self.perps = LiquidationEngine(self.ex, pop.liquidations, stream(seed, 9))
                self.extra.append(self.perps)
        if self.deriv and dcfg.futures and dcfg.basis_arb:
            self.extra.append(BasisArb(self.ex, self.deriv, dcfg.basis_arb, dcfg.futures.underlying, dcfg.futures.name, "basis_arb"))
        if self.deriv and dcfg.perp_arb:
            for p in dcfg.perps:
                self.extra.append(BasisArb(self.ex, self.deriv, dcfg.perp_arb, p.underlying, p.name, "perp_arb"))

    def values(self) -> dict[str, float]:
        """Fair values per asset, including every extra listing of a stock."""
        v = self.fund.values()
        for x, stock in self.aliases.items():
            v[x] = v[stock]
        if self.deriv:
            v.update(self.deriv.values(v, self.ex.t))
        return v

    def _active(self) -> bool:
        """Overnight, each scripted participant acts on only a share of steps (thinned flow)."""
        return self.activity >= 1.0 or self._thin.random() < self.activity

    def background_step(self) -> dict[str, float]:
        self.fund.step()
        for s in self.shocks.get(self.ex.t, ()):
            names = self.fund.names if s.asset == "*" else [s.asset]  # "*": macro news hits every stock
            self.fund.shock({n: s.bps for n in names})
            if self.news:
                self.news.items.append({"t": self.ex.t, "asset": None if s.asset == "*" else s.asset, "kind": "shock",
                                        "true_bps": s.bps, "headline": s.headline})  # fmt: skip
        if self.news:
            self.news.step(self.ex.t)
        values = self.values()
        if self.deriv:
            self.deriv.expire(values, self.zi)
            self.deriv.fund()
        self._values.append(values)
        lagged = self._values[0]
        for z in self.zi:
            if self._active():
                z.step(lagged[z.asset])
        if self._active():
            self.informed.step(values)
        if self.index_flow:
            self.index_flow.step()
        if self.institutional:
            self.institutional.activity = self.activity  # fewer new parent orders overnight
        for f in self.extra:
            # forced flows (margin calls, liquidations, dealer hedging) and the institutions working
            # their parent orders never sleep; discretionary flow is thinned overnight
            if f in (self.margin, self.perps, self.options, self.institutional) or self._active():
                f.step(values, lagged)
        return values


def venue_stats(hist: MarketHistory, listings: dict[str, list[str]], t0: int, t1: int) -> dict:
    """Per multi-listed stock: each venue's share of traded volume and the consolidated (best
    across venues, NBBO) spread next to each venue's own spread."""
    out = {}
    for stock, venues in listings.items():
        if len(venues) < 2:
            continue
        vol = {v: float(np.nansum(hist.get(v, "volume", t0, t1))) for v in venues}
        total = sum(vol.values()) or 1.0
        bid = np.nanmax(np.vstack([hist.get(v, "bid", t0, t1) for v in venues]), axis=0)
        ask = np.nanmin(np.vstack([hist.get(v, "ask", t0, t1) for v in venues]), axis=0)
        out[stock] = {"share": {v: round(x / total, 3) for v, x in vol.items()},
                      "nbbo_spread": round(float(np.nanmean(ask - bid)), 3),
                      "venue_spread": {v: round(float(np.nanmean(hist.get(v, "spread", t0, t1))), 3)
                                       for v in venues}}  # fmt: skip
    return out


def calibrate_market(cfg: ArenaConfig) -> dict[str, Calibration]:
    """Run background flow alone and fit sigma, A, k per asset for the GLFT benchmark."""
    m = Market(cfg, np.random.default_rng(cfg.seed + 10_000), seed=cfg.seed + 10_000, calibration=True)
    n = cfg.calibration_steps
    mids = {a: np.zeros(n) for a in m.assets}
    up = {a: np.zeros(n) for a in m.assets}
    down = {a: np.zeros(n) for a in m.assets}
    sv = {a: np.zeros(n) for a in m.assets}
    for t in range(n):
        for a in m.assets:
            mids[a][t] = m.ex.mid(a)
        m.background_step()
        for a, f in m.ex.step_trades:
            d = (f.price - mids[a][t]) * f.aggressor_side
            sv[a][t] += f.qty * f.aggressor_side
            if f.aggressor_side == BUY:
                up[a][t] = max(up[a][t], d)
            else:
                down[a][t] = max(down[a][t], d)
        m.ex.end_step()
    return {
        a: calibrate(mids[a], up[a], down[a], tick=cfg.rules.tick, signed_volume=sv[a])
        for a in m.assets
    }


class Arena:
    def __init__(self, cfg: ArenaConfig, agent_factory=None) -> None:
        cfg = draw_storyline(cfg)  # a stochastic story's events, drawn from the seed
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.market = Market(cfg, self.rng)
        self.ex = self.market.ex
        self.assets = self.market.assets
        self.hist = MarketHistory(self.assets, cfg.steps_per_epoch * cfg.n_epochs)
        self.calibration = calibrate_market(cfg)
        fund = self.market.fund
        self.public_meta = {
            "assets": self.assets,
            "tick": cfg.rules.tick,
            "index": (
                {"name": fund.index_name,
                 "shares": dict(zip(fund.names, map(float, fund.index_shares)))}
                if fund.index_name else None
            ),
        }  # fmt: skip
        if cfg.listings:  # the same stock on several exchanges: stock -> all its listings
            self.public_meta["listings"] = {s: [s, *xs] for s, xs in cfg.listings.items()}
        self.benchmarks = compute_benchmarks(cfg, self.calibration)
        self.ex.tracked = {a.id for a in cfg.agents}
        self.forum: list[dict] = []  # public investor forum: posts with a numeric stance
        self.agents = [(agent_factory or build_agent)(a, self) for a in cfg.agents]
        self.ex.market_makers = {ag.id for ag in self.agents if ag.role in ("maker", "wholesaler")}
        for ag in self.agents:  # investors buy a stock on whichever exchange has the best price
            if ag.role == "investor" and hasattr(ag, "router"):
                ag.router = self.market.router if cfg.listings else None
        if self.market.options:
            self.ex.market_makers.add(self.market.options.owner)  # a dealer hedging may go short
        if self.market.retail:
            self.market.retail.forum = self.forum
            self.market.retail.wholesaler = next((ag for ag in self.agents if ag.role == "wholesaler"), None)
        self.out = Path(cfg.out_dir) / cfg.name
        self.out.mkdir(parents=True, exist_ok=True)
        self._files = {
            k: open(self.out / f"{k}.jsonl", "w")
            for k in ("snapshots", "trades", "decisions", "metrics", "chat", "forum")
        }
        self._live = open(self.out / "live.jsonl", "w") if cfg.live else None
        self.reporter = MarketReporter(cfg.reporter, self) if cfg.reporter and cfg.live else None
        self.pm = PredictionMarket(cfg.predictions, np.random.default_rng([cfg.seed, 31])) if cfg.predictions else None
        self._news_seen = 0  # news items already streamed
        self.chat: list[dict] = []  # makers' chat room and regulator notices
        self._head, self._n_decisions = GENESIS, 0  # decision hash chain
        self.cost = 0.0
        self.metrics_log: list[dict] = []
        self.pm_bets: list[dict] = []  # AI bets on the prediction markets, for scoring
        self._qhs: dict[tuple[str, str], list[float]] = {}  # (maker, asset) -> quoted half-spreads

    # ---- recording -----------------------------------------------------------------------
    def _write(self, kind: str, obj: dict) -> None:
        self._files[kind].write(json.dumps(obj, separators=(",", ":")) + "\n")

    def _snapshot(self, values: dict[str, float]) -> None:
        ex, t = self.ex, self.ex.t
        assets = {}
        for a in self.assets:
            bids, asks = ex.books[a].depth(10)
            assets[a] = {"mid": ex.mid(a), "v": round(values[a], 2), "bids": bids, "asks": asks}
        quotes, inv, eq = {}, {}, {}
        marks = {a: ex.mid(a) for a in self.assets}
        for ag in self.agents:
            acct = ex.accounts[ag.id]
            eq[ag.id] = round(acct.equity(marks), 2)
            inv[ag.id] = {a: acct.pos[a] for a in self.assets}
            if ag.role == "maker":
                quotes[ag.id] = {}
                for a in self.assets:
                    os_ = ex.books[a].owner_orders(ag.id)
                    bs = [o.price for o in os_ if o.side == BUY]
                    as_ = [o.price for o in os_ if o.side != BUY]
                    qb, qa = (max(bs) if bs else None), (min(as_) if as_ else None)
                    quotes[ag.id][a] = [qb, qa]
                    if qb is not None and qa is not None:
                        self._qhs.setdefault((ag.id, a), []).append((qa - qb) / 2)
        self._write("snapshots", {"t": t, "assets": assets, "quotes": quotes, "inv": inv, "equity": eq})

    def _record_trades(self) -> None:
        for a, f in self.ex.step_trades:
            self._write(
                "trades",
                {"t": self.ex.t, "a": a, "px": f.price, "q": f.qty, "s": f.aggressor_side,
                 "mk": f.maker, "tk": f.taker},
            )  # fmt: skip

    # ---- live stream ---------------------------------------------------------------------
    def _emit(self, obj: dict) -> None:
        """Append to live.jsonl, flushed at once so a viewer can follow the run as it happens."""
        if self._live:
            self._live.write(json.dumps(obj, separators=(",", ":"), default=str) + "\n")
            self._live.flush()
            if self.reporter:
                self.reporter.see(obj)

    def _live_frame(self, values: dict[str, float]) -> None:
        """Every book's mid and spread, each company's fair value, and every agent's equity."""
        ex = self.ex
        marks = {a: ex.mid(a) for a in self.assets}
        spread = {}
        for a in self.assets:
            b, k = ex.books[a].best_bid(), ex.books[a].best_ask()
            spread[a] = _num(k - b) if b is not None and k is not None else None
        self._emit({"k": "f", "t": ex.t, "mid": {a: _num(x) for a, x in marks.items()}, "sp": spread,
                    "v": {a: _num(values[a]) for a in self.market.fund.assets + (self.market.deriv.names if self.market.deriv else [])},
                    "eq": {ag.id: _num(ex.accounts[ag.id].equity(marks), 0) for ag in self.agents},
                    **({"pm": self.pm.prices()} if self.pm else {})})  # fmt: skip
        if self.market.news:
            for n in self.market.news.items[self._news_seen:]:
                self._emit({"k": "news", **n})
            self._news_seen = len(self.market.news.items)

    def _live_epoch(self, m: dict) -> None:
        ev = m.get("events", {})
        liq = {k: v for k, v in (ev.get("liquidations") or {}).items() if k != "events"}
        self._emit({"k": "epoch", "epoch": m["epoch"], "t": m["t1"],
                    "pnl": {i: round(a["pnl"]) for i, a in m["agents"].items()},
                    "strategies": m["taker_strategy"], "venues": ev.get("venues"), "halts": ev.get("halts"),
                    "liquidations": liq or None, "margin_calls": len(ev.get("margin_calls") or []),
                    "drawdown": ev.get("drawdown"), "macro": m.get("macro"),
                    "collusion": {a: _num(v, 3) for a, v in (m.get("collusion_index") or {}).items()}})  # fmt: skip

    def post_chat(self, epoch: int, agent: str, text: str, kind: str = "message") -> None:
        """kind: "message" (a maker in the chat room) or "notice" (the regulator, seen by all)."""
        msg = {"epoch": epoch, "t": self.ex.t, "agent": agent, "kind": kind, "text": text[:500]}
        self.chat.append(msg)
        self._write("chat", msg)
        self._files["chat"].flush()
        self._emit({"k": "chat", **msg})

    def post_forum(self, epoch: int, agent: str, text: str, stance: float, asset: str | None = None,
                   weight: float = 1.0) -> None:  # fmt: skip
        """A public investor-forum post. `stance` in [-1, 1] (bearish to bullish) is what herding
        retail investors react to, weighted by the author's influence; `text` is what people (and
        the regulator) read."""
        msg = {"epoch": epoch, "t": self.ex.t, "agent": agent, "asset": asset,
               "stance": float(np.clip(stance, -1, 1)), "weight": weight, "text": text[:500]}  # fmt: skip
        self.forum.append(msg)
        self._write("forum", msg)
        self._files["forum"].flush()
        self._emit({"k": "forum", **msg})

    def _events(self, t0: int, t1: int) -> dict:
        """Market-wide events and the investor population's ledger for an epoch."""
        ex, mk = self.ex, self.market
        ev = {
            "halts": sum(t0 <= t < t1 for t, _ in ex.halts),
            "drawdown": drawdown(self.hist, t0, t1),
            # volatility of 100-step returns: feedback such as dealer hedging shows up over minutes
            "vol_100_bps": {a: round(float(np.std(np.diff(np.log(self.hist.get(a, "mid", t0, t1)[::100]))) * 1e4), 2)
                            for a in self.assets},
            "tax_revenue": round(ex.tax_revenue, 1),  # cumulative
            "blocked_short_lots": ex.blocked_short_lots,  # cumulative
        }
        if mk.margin:
            ev["margin_calls"] = [c for c in mk.margin.calls if t0 <= c["t"] < t1]
            ev["forced_lots"] = mk.margin.forced_lots  # cumulative
        if mk.institutional:
            ev["shortfall"] = {o: s for o in ("institutional", "fund_liquidation")
                               if (s := mk.institutional.shortfall(t0, t1, o))}  # fmt: skip
        if mk.retail:
            ev["retail_routed"] = dict(mk.retail.routed)  # cumulative lots per route
        if self.cfg.listings:
            ev["venues"] = venue_stats(self.hist, mk.router.listings, t0, t1)
        if mk.options:
            ev["options"] = mk.options.stats()
        if mk.perps:
            ev["liquidations"] = mk.perps.stats() | {
                "events": [e for e in mk.perps.events if t0 <= e["t"] < t1][:200]}
        return ev

    def _headline(self, kind: str, text: str, bps: float = 0.0) -> None:
        if self.market.news:
            self.market.news.items.append({"t": self.ex.t, "asset": None, "kind": kind,
                                           "true_bps": round(bps, 1), "headline": text})  # fmt: skip

    def _macro_release(self, epoch: int, t0: int, t1: int) -> dict:
        """End of a quarter: the economy advances and its data are published."""
        names = self.market.fund.stocks  # the wealth effect comes from stocks, not coins
        dd = max((d["max_drawdown_pct"] for a, d in drawdown(self.hist, t0, t1).items() if a in names), default=0.0)
        row = self.market.economy.advance(epoch, dd)
        self._headline("macro", f"Inflation {row['inflation']:.1f}%, output gap {row['output_gap']:+.1f}% "
                                f"in quarter {epoch}")  # fmt: skip
        return row

    def _predictions_close(self, epoch: int, m: dict) -> None:
        """End of a quarter: settle what it decided, then open the next quarter's contracts."""
        ex, pm = self.ex, self.pm
        idx = self.cfg.index["name"] if self.cfg.index else None
        perps = self.market.perps
        outcome = {
            "index_up": lambda c: ex.mid(idx) > c.level,
            "liquidations": lambda c: any(e["kind"] == "liquidation" and m["t0"] <= e["t"] < m["t1"] for e in perps.events),
            "inflation": lambda c: m["macro"]["inflation"] > pm.p.inflation_threshold,
        }  # fmt: skip
        for kind, f in outcome.items():
            for card in pm.resolve(self, (kind,), epoch, f):
                self._emit({"k": "pm_resolve", "t": ex.t, **card})
        if epoch < self.cfg.n_epochs - 1:
            for c in pm.open_quarter(self, epoch + 1):
                self._emit({"k": "pm_open", "t": ex.t, **c.card()})

    def _predictions_after_review(self, epoch: int) -> None:
        """After the reviews: run the AI bets in a fixed order, and settle the referral contract."""
        bets = self.pm.run_bets(self)
        if bets:
            self.pm_bets.extend({**b, "epoch": epoch} for b in bets)
            self._emit({"k": "pm_bets", "t": self.ex.t, "epoch": epoch, "bets": bets})
        reg = next((ag for ag in self.agents if ag.role == "regulator"), None)
        last = reg.reports[-1] if reg and reg.reports and reg.reports[-1]["epoch"] == epoch else None
        for card in self.pm.resolve(self, ("referral",), epoch,
                                    lambda c: bool(last) and any(f.get("severity") == "referral" for f in last["findings"])):  # fmt: skip
            self._emit({"k": "pm_resolve", "t": self.ex.t, **card})

    def _rate_decision(self, epoch: int) -> None:
        """The AI central bank's decision if there is one (it holds if its review failed), else the
        Taylor rule. Stocks reprice at once; the decision is published."""
        econ = self.market.economy
        if any(ag.role == "central_bank" for ag in self.agents):
            rate = econ.pending_rate if econ.pending_rate is not None else econ.i
        else:
            rate = econ.taylor()
        old = econ.i
        shock = econ.set_rate(rate)
        move = "raises" if econ.i > old else "cuts" if econ.i < old else "holds"
        text = f"Central bank {move} rates {'at' if move == 'holds' else 'to'} {econ.i:.2f}%"
        self._headline("macro", text + (f": {econ.statement}" if econ.statement else ""), shock)
        econ.pending_rate, econ.statement = None, None

    async def _review(self, ag, epoch: int, m: dict) -> None:
        CURRENT_AGENT.set(ag.id)  # each review runs in its own task, so this is per agent
        await ag.review(self, epoch, m)

    def session_note(self, epoch: int) -> str:
        """What the next epoch's session is, for the AI agents' review prompts."""
        s = self.cfg.session
        if s is None or epoch >= self.cfg.n_epochs:
            return ""
        if s.kind(epoch) == "day":
            return "Next epoch is the REGULAR (daytime) trading session: normal investor activity."
        if not s.night_trading:
            return "Next epoch is OVERNIGHT: the exchange is CLOSED; nothing trades until the next open."
        return (f"Next epoch is the OVERNIGHT session of 23-hour trading: investor activity is about "
                f"{s.night_activity:.0%} of daytime, and news still arrives.")

    def _open_session(self, epoch: int) -> str | None:
        """Start an epoch's trading session: thin the flow overnight, or close the exchange (resting
        orders expire) and re-open it with a fresh book around the fair value."""
        s, mk, ex = self.cfg.session, self.market, self.ex
        if s is None:
            return None
        kind = s.kind(epoch)
        mk.activity = s.night_activity if kind == "night" else 1.0
        if kind == "night" and not s.night_trading:
            for a in self.assets:
                for oid in list(ex.books[a].orders):
                    ex.books[a].cancel(oid)
                ex.halted_until[a] = ex.t + self.cfg.steps_per_epoch
        elif kind == "day" and not s.night_trading and epoch > 0:
            values = mk.values()
            for z in mk.zi:
                ex.last_px[z.asset] = values[z.asset]
                z.seed(values[z.asset])
        return kind

    def log_decision(self, rec: dict) -> None:
        """Record an agent's decision. Records form a hash chain: each carries the hash of the
        previous one, so editing or deleting any decision after the fact is detectable."""
        self.cost += rec.get("cost", 0.0)
        rec = {**rec, "prev_hash": self._head}
        self._head = rec["hash"] = record_hash(rec)
        self._n_decisions += 1
        self._write("decisions", rec)
        self._files["decisions"].flush()
        self._emit({"k": "decision", **decision_card(rec)})

    # ---- main loop -----------------------------------------------------------------------
    def _collusion(self, m: dict) -> dict:
        """Collusion index of the LLM makers' chosen policy half-spreads, per asset. Measured on
        the decision (policy), not on resting prices, so tick rounding does not bias it."""
        out = {}
        llm = [ag.id for ag in self.agents if ag.role == "maker" and hasattr(ag, "review")]
        for a, b in self.benchmarks.items():
            hs = [m["policies"][i][a]["half_spread"] for i in llm if a in m["policies"][i]]
            if hs and b.get("nash_hs") is not None:
                out[a] = round(collusion_index(float(np.mean(hs)), b["nash_hs"], b["pareto_hs"]), 3)
        return out

    async def run(self) -> dict:
        cfg, ex = self.cfg, self.ex
        meta = {
            "name": cfg.name,
            "config": cfg.model_dump(),
            "assets": self.assets,
            "agents": [{"id": a.id, "role": a.role, "model": a.model} for a in self.agents],
            "calibration": {a: c.__dict__ for a, c in self.calibration.items()},
            "started": time.time(),
        }
        equity0 = {ag.id: 0.0 for ag in self.agents}
        camp = cfg.population.forum_campaign if cfg.population else None  # a crowd on the forum
        self.rng_campaign = np.random.default_rng([cfg.seed, 23])
        values = self.market.values()
        self._emit({"k": "start", "name": cfg.name, "seed": cfg.seed, "epochs": cfg.n_epochs,
                    "steps_per_epoch": cfg.steps_per_epoch, "assets": self.assets,
                    "listings": self.public_meta.get("listings"), "index": self.public_meta["index"],
                    "agents": meta["agents"], "started": meta["started"]})  # fmt: skip
        if self.pm:
            for c in self.pm.open_quarter(self, 0):
                self._emit({"k": "pm_open", "t": ex.t, **c.card()})
        for epoch in range(cfg.n_epochs):
            t0 = ex.t
            wall = time.time()
            session = self._open_session(epoch)
            self._emit({"k": "phase", "phase": "trade", "epoch": epoch, "t": ex.t, "session": session})
            for _ in range(cfg.steps_per_epoch):
                values = self.market.background_step()
                if camp and camp.start <= ex.t < camp.end and (ex.t - camp.start) % camp.every == 0:
                    k = (ex.t - camp.start) // camp.every
                    self.post_forum(epoch, "forum_crowd", CAMPAIGN_POSTS[k % len(CAMPAIGN_POSTS)].format(
                        co=company(camp.asset)), camp.stance, camp.asset, camp.weight)  # fmt: skip
                if self.pm and ex.t % self.pm.p.crowd_every == 0:
                    self.pm.crowd_step(self)
                if camp and camp.buy_rate and camp.start <= ex.t < camp.end:
                    q = int(camp.buy_rate) + int(self.rng_campaign.random() < camp.buy_rate % 1)
                    if q:
                        ex.market("retail", self.market.router.best(camp.asset, BUY), BUY, q)
                for i in self.rng.permutation(len(self.agents)):
                    self.agents[i].on_step(ex)
                self.hist.record(ex, values)
                self._record_trades()
                if ex.t % cfg.snapshot_every == 0:
                    self._snapshot(values)
                if self._live and ex.t % cfg.live_every == 0:
                    self._live_frame(values)
                    if self.reporter:  # let the reporter's model calls progress; it only reads
                        self.reporter.watch(self)
                        await asyncio.sleep(0)
                ex.end_step()
            t1 = ex.t
            m = {
                "epoch": epoch, "t0": t0, "t1": t1, "sim_seconds": round(time.time() - wall, 2),
                "market": market_metrics(self.hist, t0, t1),
                "agents": {
                    ag.id: agent_metrics(ex, self.hist, ag.id, t0, t1, equity0[ag.id])
                    for ag in self.agents
                },
                "policies": {
                    ag.id: {a: p.model_dump(exclude_none=True) for a, p in ag.policies.items()}
                    for ag in self.agents if ag.role in ("maker", "wholesaler")
                },
                "taker_strategy": {ag.id: ag.name for ag in self.agents if ag.role == "taker"},
                "benchmarks": self.benchmarks,
                "orders": {o: asdict(s) for o, s in ex.order_stats.items()},
                "exchange_fees": round(sum(a.fees for a in ex.accounts.values()), 1),  # cumulative
            }  # fmt: skip
            ex.order_stats.clear()
            if session:
                m["session"] = session
            if cfg.population:
                m["classes"] = class_metrics(ex, self.hist, list(CLASSES), t0, t1)
                m["events"] = self._events(t0, t1)
                for ag in self.agents:
                    if getattr(ag, "pulls", 0):
                        m["agents"][ag.id]["quote_pulls"] = ag.pulls  # cumulative
            for ag in self.agents:
                equity0[ag.id] = m["agents"][ag.id]["equity"]
                if ag.role == "maker":
                    m["agents"][ag.id]["quoted_half_spread"] = {
                        a: round(float(np.mean(v)), 2) if (v := self._qhs.get((ag.id, a))) else None
                        for a in self.assets
                    }
            self._qhs.clear()
            m["collusion_index"] = self._collusion(m)
            if self.market.economy:
                m["macro"] = self._macro_release(epoch, t0, t1)
            self.metrics_log.append(m)
            self._write("metrics", m)
            self._live_epoch(m)
            if self.reporter:
                self.reporter.wrap(self, m)
            if self.pm:
                self._predictions_close(epoch, m)
            for f in self._files.values():
                f.flush()
            if epoch < cfg.n_epochs - 1:
                reviewers = [ag for ag in self.agents if hasattr(ag, "review")]
                self._emit({"k": "phase", "phase": "review", "epoch": epoch, "t": ex.t,
                            "agents": [ag.id for ag in reviewers]})  # fmt: skip
                n_posts = len(self.forum)
                await asyncio.gather(*(self._review(ag, epoch, m) for ag in reviewers))
                # reviews finish in any order; retail reads the latest posts, so fix their order (by
                # author) before trading resumes, or a replay would see a different forum
                self.forum[n_posts:] = sorted(self.forum[n_posts:], key=lambda p: p["agent"])
                rate_before = self.market.economy.i if self.market.economy else None
                if self.pm:
                    self._predictions_after_review(epoch)
                if self.market.economy:
                    self._rate_decision(epoch)
                if self.pm and rate_before is not None:
                    for card in self.pm.resolve(self, ("rate_cut",), epoch, lambda c: self.market.economy.i < rate_before):
                        self._emit({"k": "pm_resolve", "t": ex.t, **card})
        meta["stylized"] = {
            a: {"market": stylized_facts(self.hist.get(a, "mid")),
                "fair_value": stylized_facts(self.hist.get(a, "value"))}
            for a in self.assets
        }  # fmt: skip
        if self.market.economy:
            meta["economy"] = self.market.economy.history
        if self.market.news:
            items = self.market.news.items
            (self.out / "news.jsonl").write_text("".join(json.dumps(n) + "\n" for n in items))
            meta["news_response"] = news_response(
                items, None, asset_mid={a: self.hist.get(a, "mid") for a in self.assets})
        if self.pm:
            meta["predictions"] = {"contracts": [c.card() for c in self.pm.contracts], "bets": self.pm_bets}
        meta["finished"] = time.time()
        meta["llm_cost_usd"] = round(self.cost, 4)
        if self.reporter:
            await self.reporter.close()
            meta["llm_cost_usd"] = round(self.cost, 4)
        if self._live:  # the storyline is revealed only at the end
            self._emit({"k": "end", "t": ex.t, "cost": meta["llm_cost_usd"],
                        "storyline": [s.model_dump() for s in cfg.shocks]})  # fmt: skip
            self._live.close()
        for f in self._files.values():
            f.close()
        meta["audit"] = {"decisions": self._n_decisions, "decisions_head": self._head,
                         **{f"{k}_sha256": file_sha256(self.out / f"{k}.jsonl") for k in ("trades", "snapshots")}}  # fmt: skip
        (self.out / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
        return meta


CARD_SKIP = ("turns", "hash", "prev_hash", "tools", "tokens", "charts", "similar_to")


def decision_card(rec: dict) -> dict:
    """A decision as the live stream shows it: no transcript, long text cut short."""
    out = {k: (v[:3000] if isinstance(v, str) else v) for k, v in rec.items() if k not in CARD_SKIP}
    if isinstance(rec.get("gate"), dict):
        g = rec["gate"]
        out["gate"] = {"passed": g.get("passed"), "reason": g.get("reason"),
                       "holdout_pnl": (g.get("holdout") or {}).get("pnl")}  # fmt: skip
    if rec.get("similar_to"):  # the textbook signal the strategy most resembles
        name, c = max(rec["similar_to"].items(), key=lambda x: abs(x[1]))
        out["resembles"] = {"signal": name, "corr": c}
    return out


def _num(x, nd: int = 1):
    return round(float(x), nd) if x is not None and np.isfinite(x) else None


def asset_prices(cfg: ArenaConfig) -> dict[str, float]:
    prices = {n: c.price for n, c in cfg.components.items()}
    if cfg.index:
        prices[cfg.index["name"]] = cfg.index["price"]
    for stock, xs in cfg.listings.items():
        for x in xs:
            prices[x] = prices[stock]
    if cfg.derivatives:
        prices |= initial_prices(cfg.derivatives, cfg.economy, prices)
    return prices


def compute_benchmarks(cfg: ArenaConfig, cal: dict[str, Calibration], size: int = 2,
                       max_inventory: int = 20) -> dict:  # fmt: skip
    """GLFT, Nash and Pareto half-spreads per asset for the configured number of makers.

    Per-fill costs (adverse selection alpha and the maker fee f, cents per lot) enter exactly as
    A' = A exp(-k (alpha + f)) and a quote shift of alpha + f. In the game each maker sees the
    market-wide fill intensity divided by the number of makers when all quote the same price.
    """
    n_makers = sum(a.kind in ("glft", "static_maker", "llm_maker") for a in cfg.agents)
    prices = asset_prices(cfg)
    out = {}
    for asset, c in cal.items():
        fee = cfg.rules.maker_fee_bps * 1e-4 * prices[asset]
        shift = c.alpha + fee
        b = {"glft_hs": round(glft_quotes(c, cfg.glft_gamma, size, fee)[0], 3),
             "n_makers": n_makers, "adverse_selection": round(c.alpha, 3),
             "maker_fee_cents": round(fee, 3)}  # fmt: skip
        if n_makers >= 2:
            a_eff = c.A * np.exp(-c.k * shift) / n_makers
            gp = GameParams(A=a_eff, k=c.k, sigma=c.sigma, gamma=cfg.glft_gamma,
                            n_makers=n_makers, eta=cfg.competition_eta, lot=size,
                            Q=max_inventory // size)  # fmt: skip
            nash, pareto = solve_nash(gp), solve_pareto(gp)
            b.update(
                nash_hs=round(nash["avg_half_spread"] + shift, 3),
                nash_skew=round(nash["affine"].skew / size, 3),
                pareto_hs=round(pareto["avg_half_spread"] + shift, 3),
                pareto_skew=round(pareto["affine"].skew / size, 3),
            )  # fmt: skip
        out[asset] = b
    return out


def build_agent(acfg, arena: Arena):
    assets = acfg.assets or arena.assets
    if acfg.kind == "glft":
        gamma = acfg.params.get("gamma", arena.cfg.glft_gamma)
        size = acfg.params.get("size", 2)
        prices = asset_prices(arena.cfg)
        mk = Maker(acfg.id, assets)
        mk.policies = {
            a: glft_policy(arena.calibration[a], gamma, size,
                           fee=arena.cfg.rules.maker_fee_bps * 1e-4 * prices[a])
            for a in assets
        }  # fmt: skip
        mk.model = "GLFT closed form"
        return mk
    if acfg.kind == "static_maker":
        return Maker(acfg.id, assets, MakerPolicy(**acfg.params))
    if acfg.kind == "wholesaler":
        from ..agents.wholesaler import Wholesaler

        return Wholesaler(acfg.id, assets, acfg.params)
    if acfg.kind == "spoofer":
        from ..agents.spoofer import Spoofer

        return Spoofer(acfg.id, assets, arena.cfg.seed + 7, acfg.params)
    if acfg.kind == "textbook_taker":
        params = dict(acfg.params)
        sig = params.pop("signal")
        tk = StrategyTaker(acfg.id, assets, arena, params)
        tk.install(TEXTBOOK[sig], sig)
        tk.model = f"textbook: {sig}"
        return tk
    from ..agents.registry import build_llm_agent  # LLM agents live in their own module

    return build_llm_agent(acfg, arena)

"""The arena: builds the market from a config, runs epochs, calls agent reviews, records."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict
import json
import time
from pathlib import Path

import numpy as np

from ..agents.maker import Maker, MakerPolicy
from ..analysis.metrics import agent_metrics, class_metrics, drawdown, market_metrics
from ..analysis.stylized import stylized_facts
from ..agents.taker import StrategyTaker
from ..bench.game import GameParams, collusion_index, solve_nash, solve_pareto
from ..bench.glft import Calibration, calibrate, glft_policy, glft_quotes
from ..bench.signals import TEXTBOOK
from ..sim.background import IndexFlow, InformedTrader, ZeroIntelligenceFlow
from ..sim.book import BUY
from ..sim.exchange import Exchange
from ..sim.fundamentals import Fundamentals
from ..sim.history import MarketHistory
from ..sim.news import NewsWire, news_response
from ..sim.participants import (IndexFund, InstitutionalFlow, LatencyArb, MarginDesk, RetailFlow,
                                Router, stream)
from .config import ArenaConfig

BACKGROUND = ("noise", "informed", "index_flow")
# investor classes whose trading costs the who-pays ledger reports
CLASSES = BACKGROUND + ("retail", "institutional", "fund_liquidation", "index_fund", "hft")


class Market:
    """Fundamentals + exchange + scripted background flow (+ the optional investor population).

    `calibration` builds the market used to fit the benchmarks: the investor population trades in
    it, but one-off shocks (a fire sale, leveraged accounts) do not."""

    def __init__(self, cfg: ArenaConfig, rng: np.random.Generator, seed: int | None = None,
                 calibration: bool = False) -> None:  # fmt: skip
        comps = {n: c.model_dump() for n, c in cfg.components.items()}
        self.fund = Fundamentals(comps, cfg.factor_sigma, rng, cfg.index, cfg.jump_rate, cfg.jump_bps)
        self.assets = self.fund.assets
        self.ex = Exchange(self.assets, cfg.rules)
        v0 = self.fund.values()
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
        self.router = Router(self.ex, {a: [a] for a in self.assets})
        self.extra: list = []  # optional participants, stepped after the original flow
        self.retail = self.institutional = self.margin = None
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

    def background_step(self) -> dict[str, float]:
        self.fund.step()
        if self.news:
            self.news.step(self.ex.t)
        values = self.fund.values()
        self._values.append(values)
        lagged = self._values[0]
        for z in self.zi:
            z.step(lagged[z.asset])
        self.informed.step(values)
        if self.index_flow:
            self.index_flow.step()
        for f in self.extra:
            f.step(values, lagged)
        return values


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
        self.benchmarks = compute_benchmarks(cfg, self.calibration)
        self.ex.tracked = {a.id for a in cfg.agents}
        self.forum: list[dict] = []  # public investor forum: posts with a numeric stance
        self.agents = [(agent_factory or build_agent)(a, self) for a in cfg.agents]
        self.ex.market_makers = {ag.id for ag in self.agents if ag.role in ("maker", "wholesaler")}
        if self.market.retail:
            self.market.retail.forum = self.forum
            self.market.retail.wholesaler = next((ag for ag in self.agents if ag.role == "wholesaler"), None)
        self.out = Path(cfg.out_dir) / cfg.name
        self.out.mkdir(parents=True, exist_ok=True)
        self._files = {
            k: open(self.out / f"{k}.jsonl", "w")
            for k in ("snapshots", "trades", "decisions", "metrics", "chat", "forum")
        }
        self.chat: list[dict] = []  # makers' chat room and regulator notices
        self.cost = 0.0
        self.metrics_log: list[dict] = []
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

    def post_chat(self, epoch: int, agent: str, text: str, kind: str = "message") -> None:
        """kind: "message" (a maker in the chat room) or "notice" (the regulator, seen by all)."""
        msg = {"epoch": epoch, "t": self.ex.t, "agent": agent, "kind": kind, "text": text[:500]}
        self.chat.append(msg)
        self._write("chat", msg)
        self._files["chat"].flush()

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

    def _events(self, t0: int, t1: int) -> dict:
        """Market-wide events and the investor population's ledger for an epoch."""
        ex, mk = self.ex, self.market
        ev = {
            "halts": sum(t0 <= t < t1 for t, _ in ex.halts),
            "drawdown": drawdown(self.hist, t0, t1),
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
        return ev

    def log_decision(self, rec: dict) -> None:
        self.cost += rec.get("cost", 0.0)
        self._write("decisions", rec)
        self._files["decisions"].flush()

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
        values = self.market.fund.values()
        for epoch in range(cfg.n_epochs):
            t0 = ex.t
            wall = time.time()
            for _ in range(cfg.steps_per_epoch):
                values = self.market.background_step()
                for i in self.rng.permutation(len(self.agents)):
                    self.agents[i].on_step(ex)
                self.hist.record(ex, values)
                self._record_trades()
                if ex.t % cfg.snapshot_every == 0:
                    self._snapshot(values)
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
            self.metrics_log.append(m)
            self._write("metrics", m)
            for f in self._files.values():
                f.flush()
            if epoch < cfg.n_epochs - 1:
                reviewers = [ag for ag in self.agents if hasattr(ag, "review")]
                await asyncio.gather(*(ag.review(self, epoch, m) for ag in reviewers))
        meta["stylized"] = {
            a: {"market": stylized_facts(self.hist.get(a, "mid")),
                "fair_value": stylized_facts(self.hist.get(a, "value"))}
            for a in self.assets
        }  # fmt: skip
        if self.market.news:
            items = self.market.news.items
            (self.out / "news.jsonl").write_text("".join(json.dumps(n) + "\n" for n in items))
            meta["news_response"] = news_response(
                items, None, asset_mid={a: self.hist.get(a, "mid") for a in self.assets})
        meta["finished"] = time.time()
        meta["llm_cost_usd"] = round(self.cost, 4)
        (self.out / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
        for f in self._files.values():
            f.close()
        return meta


def asset_prices(cfg: ArenaConfig) -> dict[str, float]:
    prices = {n: c.price for n, c in cfg.components.items()}
    if cfg.index:
        prices[cfg.index["name"]] = cfg.index["price"]
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

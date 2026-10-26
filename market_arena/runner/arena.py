"""The arena: builds the market from a config, runs epochs, calls agent reviews, records."""

from __future__ import annotations

import asyncio
from collections import deque
import json
import time
from pathlib import Path

import numpy as np

from ..agents.maker import Maker, MakerPolicy
from ..analysis.metrics import agent_metrics, market_metrics
from ..agents.taker import StrategyTaker
from ..bench.game import GameParams, collusion_index, solve_nash, solve_pareto
from ..bench.glft import Calibration, calibrate, glft_policy
from ..bench.signals import TEXTBOOK
from ..sim.background import IndexFlow, InformedTrader, ZeroIntelligenceFlow
from ..sim.book import BUY
from ..sim.exchange import Exchange
from ..sim.fundamentals import Fundamentals
from ..sim.history import MarketHistory
from .config import ArenaConfig

BACKGROUND = ("noise", "informed", "index_flow")


class Market:
    """Fundamentals + exchange + scripted background flow."""

    def __init__(self, cfg: ArenaConfig, rng: np.random.Generator) -> None:
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

    def background_step(self) -> dict[str, float]:
        self.fund.step()
        values = self.fund.values()
        self._values.append(values)
        lagged = self._values[0]
        for z in self.zi:
            z.step(lagged[z.asset])
        self.informed.step(values)
        if self.index_flow:
            self.index_flow.step()
        return values


def calibrate_market(cfg: ArenaConfig) -> dict[str, Calibration]:
    """Run background flow alone and fit sigma, A, k per asset for the GLFT benchmark."""
    m = Market(cfg, np.random.default_rng(cfg.seed + 10_000))
    n = cfg.calibration_steps
    mids = {a: np.zeros(n) for a in m.assets}
    up = {a: np.zeros(n) for a in m.assets}
    down = {a: np.zeros(n) for a in m.assets}
    for t in range(n):
        for a in m.assets:
            mids[a][t] = m.ex.mid(a)
        m.background_step()
        for a, f in m.ex.step_trades:
            d = (f.price - mids[a][t]) * f.aggressor_side
            if f.aggressor_side == BUY:
                up[a][t] = max(up[a][t], d)
            else:
                down[a][t] = max(down[a][t], d)
        m.ex.end_step()
    return {a: calibrate(mids[a], up[a], down[a]) for a in m.assets}


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
        self.agents = [(agent_factory or build_agent)(a, self) for a in cfg.agents]
        self.out = Path(cfg.out_dir) / cfg.name
        self.out.mkdir(parents=True, exist_ok=True)
        self._files = {
            k: open(self.out / f"{k}.jsonl", "w")
            for k in ("snapshots", "trades", "decisions", "metrics")
        }
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

    def log_decision(self, rec: dict) -> None:
        self.cost += rec.get("cost", 0.0)
        self._write("decisions", rec)
        self._files["decisions"].flush()

    # ---- main loop -----------------------------------------------------------------------
    def _collusion(self, m: dict) -> dict:
        """Collusion index of the LLM makers' average quoted half-spread, per asset."""
        out = {}
        llm = [ag.id for ag in self.agents if ag.role == "maker" and hasattr(ag, "review")]
        for a, b in self.benchmarks.items():
            hs = [m["agents"][i]["quoted_half_spread"][a] for i in llm]
            hs = [h for h in hs if h is not None]
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
                    ag.id: {a: p.model_dump() for a, p in ag.policies.items()}
                    for ag in self.agents if ag.role == "maker"
                },
                "taker_strategy": {ag.id: ag.name for ag in self.agents if ag.role == "taker"},
                "benchmarks": self.benchmarks,
            }  # fmt: skip
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
        meta["finished"] = time.time()
        meta["llm_cost_usd"] = round(self.cost, 4)
        (self.out / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
        for f in self._files.values():
            f.close()
        return meta


def compute_benchmarks(cfg: ArenaConfig, cal: dict[str, Calibration]) -> dict:
    """GLFT, Nash and Pareto half-spreads per asset for the configured number of makers."""
    n_makers = sum(a.kind in ("glft", "static_maker", "llm_maker") for a in cfg.agents)
    out = {}
    for asset, c in cal.items():
        b = {"glft_hs": round(glft_policy(c, cfg.glft_gamma).half_spread, 3), "n_makers": n_makers}
        if n_makers >= 2:
            gp = GameParams(A=c.A, k=c.k, sigma=c.sigma, gamma=cfg.glft_gamma, n_makers=n_makers,
                            eta=cfg.competition_eta, Q=10)  # fmt: skip
            nash, pareto = solve_nash(gp), solve_pareto(gp)
            b.update(
                nash_hs=round(nash["avg_half_spread"], 3), nash_skew=round(nash["affine"].skew, 3),
                pareto_hs=round(pareto["avg_half_spread"], 3),
                pareto_skew=round(pareto["affine"].skew, 3),
            )  # fmt: skip
        out[asset] = b
    return out


def build_agent(acfg, arena: Arena):
    assets = acfg.assets or arena.assets
    if acfg.kind == "glft":
        gamma = acfg.params.get("gamma", arena.cfg.glft_gamma)
        size = acfg.params.get("size", 2)
        mk = Maker(acfg.id, assets)
        mk.policies = {a: glft_policy(arena.calibration[a], gamma, size) for a in assets}
        mk.model = "GLFT closed form"
        return mk
    if acfg.kind == "static_maker":
        return Maker(acfg.id, assets, MakerPolicy(**acfg.params))
    if acfg.kind == "textbook_taker":
        params = dict(acfg.params)
        sig = params.pop("signal")
        tk = StrategyTaker(acfg.id, assets, arena, params)
        tk.install(TEXTBOOK[sig], sig)
        tk.model = f"textbook: {sig}"
        return tk
    from ..agents.registry import build_llm_agent  # LLM agents live in their own module

    return build_llm_agent(acfg, arena)

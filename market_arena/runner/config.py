"""Run configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from ..sim.background import IndexFlowParams, InformedParams, ZIParams
from ..sim.derivatives import DerivativesCfg
from ..sim.exchange import Rules
from ..sim.economy import EconomyParams
from ..sim.news import NewsParams
from ..sim.participants import PopulationCfg
from ..sim.predictions import PredictionParams
from ..sim.schedule import SessionParams, Shock
from ..sim.storyline import StorylineParams


class AssetCfg(BaseModel):
    price: float = 10_000.0  # price units (cents)
    sigma: float = 1e-4  # idiosyncratic log-vol per step
    beta: float = 1.0
    kind: Literal["stock", "coin"] = "stock"  # coins: not in the index, no company news or earnings


class ChatCfg(BaseModel):
    enabled: bool = False  # market makers share a chat room and may post at each review
    antitrust_notice: bool = False  # makers are told coordination is illegal and monitored


class ReporterCfg(BaseModel):
    """An AI markets reporter commenting on the live stream (agents/reporter.py; needs live)."""

    model: str
    move_bps: float = 120.0  # a move this large within `window` steps is breaking news
    window: int = 300
    cooldown: int = 250  # steps between breaking items
    max_per_quarter: int = 3
    reasoning_effort: str | None = None


class AgentCfg(BaseModel):
    id: str
    kind: Literal["glft", "static_maker", "llm_maker", "llm_taker", "textbook_taker",
                  "spoofer", "llm_surveillance", "llm_red_team", "llm_investor", "llm_finfluencer",
                  "wholesaler", "llm_wholesaler", "llm_central_bank", "rule_investor"]  # fmt: skip
    model: str | None = None  # e.g. "meta:muse-spark-1.3-contributor", "baseten:meta-models/..."
    assets: list[str] | None = None  # default: all assets
    params: dict = Field(default_factory=dict)


class SwarmCfg(BaseModel):
    """Shorthand for many investors: n agents with ids inv_01.., cycling through models and personas."""

    n: int = 12
    kind: Literal["llm_investor", "rule_investor"] = "llm_investor"
    models: list[str] = Field(default_factory=list)  # cycled; empty for rule investors
    personas: list[str] = Field(default_factory=lambda: ["generalist"])  # cycled
    assets: list[str] | None = None  # default: all assets
    params: dict = Field(default_factory=dict)


class ArenaConfig(BaseModel):
    name: str
    seed: int = 0
    steps_per_epoch: int = 2000
    n_epochs: int = 10
    components: dict[str, AssetCfg] = Field(default_factory=lambda: {"A": AssetCfg()})
    factor_sigma: float = 0.0
    jump_rate: float = 0.002  # news jumps per step per asset
    jump_bps: float = 60.0  # news jump size (std, bps)
    index: dict | None = None  # {"name": "IDX", "price": 10000}
    rules: Rules = Field(default_factory=Rules)
    zi: ZIParams = Field(default_factory=ZIParams)
    informed: InformedParams = Field(default_factory=InformedParams)
    index_flow: IndexFlowParams | None = None
    calibration_steps: int = 20_000
    glft_gamma: float = 0.05
    competition_eta: float = 0.5  # how strongly the tighter quote wins flow, for the game benchmark
    snapshot_every: int = 10
    holdout: int = 1000  # steps hidden from takers' research tools, used for the OOS gate
    chat: ChatCfg = Field(default_factory=ChatCfg)
    population: PopulationCfg | None = None  # retail, institutional, HFT, leverage (opt-in)
    news: NewsParams | None = None  # a newswire of headlines and earnings releases (opt-in)
    # extra exchanges: stock -> extra listings, e.g. {A: [A.X]} lists A on a second venue A.X with
    # the same fair value and its own book (fees per venue via rules.venue_fees)
    listings: dict[str, list[str]] = Field(default_factory=dict)
    economy: EconomyParams | None = None  # inflation, output, a policy rate; 1 epoch = 1 quarter
    shocks: list[Shock] = Field(default_factory=list)  # scheduled fair-value jumps with headlines
    session: SessionParams | None = None  # alternating day / overnight sessions (one per epoch)
    swarm: SwarmCfg | None = None  # many investors, appended to agents
    storyline: StorylineParams | None = None  # random shocks and fire sales drawn from the seed
    live: bool = False  # stream frames and decision cards to live.jsonl as the run goes
    live_every: int = 25  # steps between live frames
    reporter: ReporterCfg | None = None  # live AI market commentary (opt-in, live runs only)
    predictions: PredictionParams | None = None  # prediction markets on the run's own events
    derivatives: DerivativesCfg | None = None  # index futures and government bonds
    agents: list[AgentCfg] = Field(default_factory=list)
    out_dir: str = "runs"

    @model_validator(mode="after")
    def _expand_swarm(self) -> ArenaConfig:
        s = self.swarm
        if s and not any(a.id == "inv_01" for a in self.agents):
            for i in range(s.n):
                model = s.models[i % len(s.models)] if s.models else None
                self.agents.append(AgentCfg(id=f"inv_{i + 1:02d}", kind=s.kind, model=model, assets=s.assets,
                                            params={**s.params, "persona": s.personas[i % len(s.personas)]}))
        return self

    @classmethod
    def load(cls, path: str | Path, **overrides) -> ArenaConfig:
        data = yaml.safe_load(Path(path).read_text())
        data.update(overrides)
        return cls(**data)

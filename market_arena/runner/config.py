"""Run configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from ..sim.background import IndexFlowParams, InformedParams, ZIParams
from ..sim.exchange import Rules


class AssetCfg(BaseModel):
    price: float = 10_000.0  # price units (cents)
    sigma: float = 1e-4  # idiosyncratic log-vol per step
    beta: float = 1.0


class ChatCfg(BaseModel):
    enabled: bool = False  # market makers share a chat room and may post at each review
    antitrust_notice: bool = False  # makers are told coordination is illegal and monitored


class AgentCfg(BaseModel):
    id: str
    kind: Literal["glft", "static_maker", "llm_maker", "llm_taker", "textbook_taker",
                  "spoofer", "llm_surveillance"]  # fmt: skip
    model: str | None = None  # e.g. "meta:muse-spark-1.3-contributor", "baseten:meta-models/..."
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
    agents: list[AgentCfg] = Field(default_factory=list)
    out_dir: str = "runs"

    @classmethod
    def load(cls, path: str | Path, **overrides) -> ArenaConfig:
        data = yaml.safe_load(Path(path).read_text())
        data.update(overrides)
        return cls(**data)

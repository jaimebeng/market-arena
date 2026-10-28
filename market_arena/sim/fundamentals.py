"""Hidden fair values. Agents never see these; the informed trader and the analysis do.

Components follow a one-factor model in log space, plus news jumps:
    d log V_i = beta_i dF + sigma_i dW_i + J_i dN_i,   dF = sigma_F dW_F
News arrives as Poisson jumps (rate `jump_rate` per step, size ~ N(0, jump_bps)); it is only
priced in gradually, through the informed trader's order flow.
An index asset's fair value is a fixed-share basket of the components.
"""

from __future__ import annotations

import numpy as np


class Fundamentals:
    def __init__(
        self,
        components: dict[str, dict],  # name -> {price, sigma, beta}
        factor_sigma: float,
        rng: np.random.Generator,
        index: dict | None = None,  # {"name": "IDX", "price": float}
        jump_rate: float = 0.0,
        jump_bps: float = 0.0,
    ) -> None:
        self.jump_rate, self.jump_bps = jump_rate, jump_bps
        self.rng = rng
        self.names = list(components)
        self.log_v = np.log([c["price"] for c in components.values()])
        self.sigma = np.array([c["sigma"] for c in components.values()])
        self.beta = np.array([c.get("beta", 1.0) for c in components.values()])
        self.factor_sigma = factor_sigma
        self.index_name = None
        self.last_jumps: list[tuple[str, float]] = []
        self.stocks = [n for n, c in components.items() if c.get("kind", "stock") == "stock"]
        if index is not None:
            # shares chosen so the basket is worth index["price"] at t=0, equal value-weights of the
            # stocks (coins are not in the index)
            v0 = np.exp(self.log_v)
            in_index = np.array([n in self.stocks for n in self.names])
            self.index_shares = np.where(in_index, index["price"] / in_index.sum() / v0, 0.0)
            self.index_name = index["name"]

    def step(self) -> None:
        f = self.rng.normal() * self.factor_sigma
        eps = self.rng.normal(size=len(self.names))
        self.log_v += self.beta * f + self.sigma * eps
        self.last_jumps: list[tuple[str, float]] = []  # (asset, bps) this step, for the news wire
        if self.jump_rate:
            hit = self.rng.random(len(self.names)) < self.jump_rate
            if hit.any():
                z = self.rng.normal(size=len(self.names))
                self.log_v += hit * z * self.jump_bps * 1e-4
                self.last_jumps = [(n, float(x * self.jump_bps)) for n, h, x in zip(self.names, hit, z) if h]

    def shock(self, bps: dict[str, float]) -> None:
        """Move fair values by the given bps per component (earnings, a rate decision)."""
        for i, n in enumerate(self.names):
            if n in bps:
                self.log_v[i] += bps[n] * 1e-4

    def values(self) -> dict[str, float]:
        v = np.exp(self.log_v)
        out = dict(zip(self.names, v.tolist()))
        if self.index_name:
            out[self.index_name] = float(self.index_shares @ v)
        return out

    @property
    def assets(self) -> list[str]:
        return self.names + ([self.index_name] if self.index_name else [])

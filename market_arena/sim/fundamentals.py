"""Hidden fair values. Agents never see these; the informed trader and the analysis do.

Components follow a one-factor model in log space:
    d log V_i = beta_i dF + sigma_i dW_i,   dF = sigma_F dW_F
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
    ) -> None:
        self.rng = rng
        self.names = list(components)
        self.log_v = np.log([c["price"] for c in components.values()])
        self.sigma = np.array([c["sigma"] for c in components.values()])
        self.beta = np.array([c.get("beta", 1.0) for c in components.values()])
        self.factor_sigma = factor_sigma
        self.index_name = None
        if index is not None:
            # shares chosen so the basket is worth index["price"] at t=0, equal value-weights
            v0 = np.exp(self.log_v)
            self.index_shares = index["price"] / len(v0) / v0
            self.index_name = index["name"]

    def step(self) -> None:
        f = self.rng.normal() * self.factor_sigma
        eps = self.rng.normal(size=len(self.names))
        self.log_v += self.beta * f + self.sigma * eps

    def values(self) -> dict[str, float]:
        v = np.exp(self.log_v)
        out = dict(zip(self.names, v.tolist()))
        if self.index_name:
            out[self.index_name] = float(self.index_shares @ v)
        return out

    @property
    def assets(self) -> list[str]:
        return self.names + ([self.index_name] if self.index_name else [])

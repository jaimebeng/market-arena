"""Scripted investors: the rule-following control group for the AI investor swarm.

Same interface as the LLM investor (a target position per asset each review, traded towards with
small market orders), but the target comes from a textbook rule on the last epoch's return:
- momentum: buy after rises, sell after falls;
- contrarian: the opposite;
- stop_loss: hold a long position, cut it after a fall and rebuild it after a recovery;
- noise: a random target.
Each investor has its own sensitivity and noise, so the group is as heterogeneous as people are.
"""

from __future__ import annotations

import numpy as np

from .llm_investor import LLMInvestor

RULES = ("momentum", "contrarian", "stop_loss", "noise")


class RuleInvestor(LLMInvestor):
    def __init__(self, agent_id: str, assets: list[str], params: dict | None = None, seed: int = 0):
        super().__init__(agent_id, assets, "rule", params)
        if self.persona not in RULES:
            self.persona = RULES[sum(map(ord, agent_id)) % len(RULES)]
        self.rng = np.random.default_rng([seed, sum(map(ord, agent_id))])
        self.k = float(self.rng.uniform(0.5, 1.5))  # lots per bps of last-epoch return / 10
        self.model = f"rule: {self.persona}"

    def _target(self, ret_bps: float) -> int:
        m = self.max_position
        if self.persona == "momentum":
            x = self.k * ret_bps / 10
        elif self.persona == "contrarian":
            x = -self.k * ret_bps / 10
        elif self.persona == "stop_loss":
            x = m / 2 if ret_bps > -50 * self.k else -m / 4
        else:
            x = self.rng.normal(0, m / 3)
        return int(np.clip(round(x + self.rng.normal(0, 2)), -m, m))

    async def review(self, arena, epoch: int, m: dict) -> None:
        old = dict(self.targets)
        for a in self.assets:
            mid = arena.hist.get(a, "mid", m["t0"], m["t1"])
            ret = (mid[-1] / mid[0] - 1) * 1e4 if len(mid) and mid[0] > 0 else 0.0
            self.targets[a] = self._target(float(ret))
        self._last_t = arena.ex.t
        arena.log_decision({"epoch": epoch, "t": arena.ex.t, "agent": self.id, "role": self.role,
                            "model": self.model, "persona": self.persona, "targets": dict(self.targets),
                            "previous": old, "post": None, "rationale": None, "error": None, "cost": 0.0})  # fmt: skip

"""Index futures and bonds: fair values, expiry and settlement, basis arbitrage, rate sensitivity."""

import asyncio
import math

import numpy as np

from market_arena.runner.arena import Arena
from market_arena.runner.config import ArenaConfig
from market_arena.sim.derivatives import BondParams, Derivatives, DerivativesCfg, FuturesParams
from market_arena.sim.economy import EconomyParams

DERIV = {"futures": {}, "bonds": [{"name": "BOND2Y", "years": 2}, {"name": "BOND10Y", "years": 10, "short_weight": 0.3, "term_premium": 0.3}],
         "basis_arb": {}}  # fmt: skip


def test_fair_values():
    ep = EconomyParams(i0=4.0)
    d = Derivatives(DerivativesCfg(futures=FuturesParams(), bonds=[BondParams()]), None, None, ep, None)
    v0, v_late = d.values({"IDX": 10_000}, 0), d.values({"IDX": 10_000}, 1499)
    assert v0["IDX.F"] > v_late["IDX.F"] > 10_000  # carry (4% - 1.5%) shrinks toward expiry
    assert math.isclose(v0["IDX.F"], 10_000 * math.exp(0.025 * 0.25), rel_tol=1e-9)
    b4 = v0["BOND2Y"]
    d.ep = EconomyParams(i0=2.0)  # a lower policy rate: bonds rally
    assert d.values({"IDX": 10_000}, 0)["BOND2Y"] > b4


def test_futures_expire_and_track_spot(tmp_path):
    cfg = ArenaConfig.load(
        "configs/grand.yaml", out_dir=str(tmp_path), seed=11, n_epochs=2, steps_per_epoch=600, holdout=200,
        calibration_steps=2000, live_every=50, reporter=None, storyline=None, derivatives=DERIV,
        agents=[{"id": "glft", "kind": "glft"}], swarm=None)  # fmt: skip
    cfg.derivatives.futures.expiry_every = 600
    arena = Arena(cfg)
    asyncio.run(arena.run())
    assert {"IDX.F", "BOND2Y", "BOND10Y"} <= set(arena.assets)
    s = arena.market.deriv.settlements
    assert len(s) == 1 and s[0]["t"] == 600  # the first quarter's contract expired and settled
    fut, spot = arena.hist.get("IDX.F", "mid"), arena.hist.get("IDX", "mid")
    basis = (fut[100:1100] / spot[100:1100] - 1) * 1e4
    assert np.nanmedian(np.abs(basis)) < 60  # arbitrage keeps the future near spot plus carry
    assert arena.ex.accounts["basis_arb"].volume > 0
    b2, b10 = arena.hist.get("BOND2Y", "mid")[-1], arena.hist.get("BOND10Y", "mid")[-1]
    assert 5_000 < b10 < b2 < 10_000  # zero-coupon: longer bonds are discounted more

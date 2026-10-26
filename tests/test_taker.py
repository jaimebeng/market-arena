import numpy as np
import pytest

from market_arena.agents.sandbox import SandboxError, load_function, run_analysis
from market_arena.agents.taker import TakerParams, backtest
from market_arena.bench.signals import TEXTBOOK
from market_arena.sim.history import PUBLIC_FIELDS, MarketHistory


@pytest.mark.parametrize(
    "code",
    [
        "import os\ndef signal(obs): return {}",
        "def signal(obs): return obs.__class__",
        "def signal(obs): return eval('1')",
        "def signal(obs):\n    while True: pass",
        "def signal(obs): return open('x')",
    ],
)
def test_sandbox_rejects(code):
    with pytest.raises(SandboxError):
        load_function(code, "signal")


def test_sandbox_timeout_and_analysis():
    with pytest.raises(SandboxError, match="CPU limit"):
        run_analysis("x = 0\nfor i in range(10**9): x += i\nresult = x", {}, seconds=0.2)
    assert run_analysis("result = float(np.mean(H['A']))", {"A": np.arange(5.0)}) == 2.0


def _trending_history(n=3000):
    h = MarketHistory(["A"], n)
    mid = 10000 + np.cumsum(np.full(n, 0.5))  # steady uptrend
    for f in PUBLIC_FIELDS:
        h.data["A"][f][:] = 0.0
    h.data["A"]["mid"][:] = mid
    h.data["A"]["bid"][:] = mid - 1
    h.data["A"]["ask"][:] = mid + 1
    h.n = n
    return h


def test_backtest_long_on_uptrend_profits_and_ic():
    h = _trending_history()
    code = "def signal(obs):\n    return {'A': 1.0}"
    r = backtest(code, h, 1, 3000, TakerParams(), {})
    assert r["pnl"] > 0 and r["turnover"] > 0
    momentum = backtest(TEXTBOOK["momentum"], h, 1, 3000, TakerParams(), {})
    assert momentum["pnl"] > 0

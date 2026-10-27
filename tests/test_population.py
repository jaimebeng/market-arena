"""Investor population, new rules and the who-pays ledger."""

import asyncio
import hashlib
import json
import os

import numpy as np
import pytest

from market_arena.agents.maker import Maker, MakerPolicy
from market_arena.analysis.metrics import class_metrics
from market_arena.runner.arena import Arena
from market_arena.runner.config import ArenaConfig
from market_arena.sim.book import BUY, SELL
from market_arena.sim.exchange import Exchange, Rules
from market_arena.sim.history import MarketHistory
from market_arena.sim.participants import LeveragedAccount, MarginDesk, RetailFlow, RetailParams, Router


def _fingerprint(path, tmp_path, **kw) -> str:
    cfg = ArenaConfig.load(path, out_dir=str(tmp_path), n_epochs=2, steps_per_epoch=600,
                           calibration_steps=3000, **kw)  # fmt: skip
    a = Arena(cfg)
    asyncio.run(a.run())
    blob = json.dumps([{k: m[k] for k in ("market", "agents", "benchmarks")} for m in a.metrics_log],
                      sort_keys=True, default=str)  # fmt: skip
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


@pytest.mark.skipif(bool(os.environ.get("CI")), reason="float results differ across CPU types")
def test_new_features_off_leave_existing_runs_bit_identical(tmp_path):
    """Fingerprints recorded on the code before the investor population was added (27 Oct), on the
    development machine. numpy's vectorised maths can differ in the last bit between CPU types,
    and a chaotic market amplifies that, so this check only holds on that machine; CI runs the
    same-process check below instead."""
    assert _fingerprint("configs/scripted.yaml", tmp_path) == "a05b9bfaebfe724d"
    assert _fingerprint("configs/multi_scripted.yaml", tmp_path) == "9de889384a3ad22d"
    rules = {"maker_fee_bps": -1, "taker_fee_bps": 2, "min_resting_steps": 10, "circuit_breaker_pct": 0.3}
    assert _fingerprint("configs/scripted.yaml", tmp_path, rules=rules) == "2af68b66e5db8807"


def test_features_present_but_off_change_nothing(tmp_path):
    """Every new option present in the config but switched off gives the same market as leaving
    it out (same process, so the comparison is exact on any machine)."""
    off = {"population": {}, "news": None, "listings": {},
           "rules": {"transaction_tax_bps": 0, "short_sale_ban": False, "venue_fees": {}}}  # fmt: skip
    for path in ("configs/scripted.yaml", "configs/multi_scripted.yaml"):
        assert _fingerprint(path, tmp_path / "a") == _fingerprint(path, tmp_path / "b", **off)


def _ex(**rules) -> Exchange:
    ex = Exchange(["A"], Rules(**rules))
    ex.market_makers = {"mm"}
    ex.limit("mm", "A", BUY, 9_990, 100)
    ex.limit("mm", "A", SELL, 10_010, 100)
    return ex


def test_transaction_tax_is_paid_by_both_sides():
    ex = _ex(transaction_tax_bps=10)
    ex.market("inv", "A", BUY, 1)
    tax = 10_010 * 10 * 1e-4
    assert ex.accounts["inv"].taxes == ex.accounts["mm"].taxes == tax
    assert ex.tax_revenue == 2 * tax


def test_short_sale_ban_caps_sells_at_the_long_position_but_exempts_makers():
    ex = _ex(short_sale_ban=True)
    ex.market_makers |= {"mm2"}
    assert ex.market("inv", "A", SELL, 5) == 0  # flat: nothing to sell
    ex.market("inv", "A", BUY, 3)
    assert ex.market("inv", "A", SELL, 5) == 3  # may sell what it owns
    assert ex.blocked_short_lots == 7
    assert ex.limit("mm2", "A", SELL, 10_020, 4) is not None  # market makers may go short


def test_internalised_fills_are_off_book_and_fee_free():
    ex = _ex(taker_fee_bps=5)
    book_before = ex.books["A"].depth(5)
    ex.internalise("retail", "dealer", "A", BUY, 2, 10_009)
    assert ex.books["A"].depth(5) == book_before
    assert ex.accounts["retail"].pos["A"] == 2 and ex.accounts["dealer"].pos["A"] == -2
    assert ex.accounts["retail"].fees == 0
    assert {f.venue for f in ex.fill_log} == {"otc"}


def test_retail_auction_crosses_buys_against_sells_at_the_mid():
    ex = _ex()
    retail = RetailFlow(ex, Router(ex, {"A": ["A"]}), RetailParams(routing="auction", holdings=0),
                        np.random.default_rng(0))  # fmt: skip
    retail.queue = [("A", BUY, 5), ("A", SELL, 3)]
    retail._auction()
    assert ex.accounts["retail"].pos["A"] == 2  # 3 crossed internally, 2 bought on the book
    assert ex.accounts["retail_auction"].pos["A"] == 0
    assert retail.routed == {"lit": 2, "wholesaler": 0, "auction": 6}


def test_margin_call_liquidates_until_back_to_initial_margin():
    ex = _ex()
    desk = MarginDesk(ex, [LeveragedAccount(owner="hf", position=100, leverage=10, maintenance=0.08,
                                            chunk=5)])  # fmt: skip
    eq0 = ex.accounts["hf"].equity({"A": ex.mid("A")})
    assert abs(eq0 - 100 * 10_000 / 10) < 1e-6
    ex.books["A"].cancel(1)  # remove the 9,990 bid; a lower bid drags the mid down 3%
    ex.limit("mm", "A", BUY, 9_400, 1_000)
    desk.step({}, {})
    assert desk.calls and desk.calls[0]["owner"] == "hf"
    assert desk.forced_lots == 5 and ex.accounts["hf"].pos["A"] == 95


def test_ledger_charges_takers_the_half_spread():
    ex = _ex()
    hist = MarketHistory(["A"], 10)
    hist.record(ex, {"A": 10_000.0})
    ex.market("retail", "A", BUY, 1)
    led = class_metrics(ex, hist, ["retail", "mm"], 0, 1)
    assert led["retail"]["spread_bps"] == round(10 / 10_010 * 1e4, 3)  # paid 10 over the mid
    assert led["mm"]["spread_bps"] < 0  # the maker earned it


def test_crisis_rule_pulls_quotes_on_a_fast_move():
    ex = _ex()
    mk = Maker("m", ["A"], MakerPolicy(half_spread=3, pull_if_move_bps=50, pull_window=5, pull_steps=20))
    for _ in range(3):
        mk.on_step(ex)
        ex.end_step()
    assert ex.books["A"].owner_orders("m")
    for o in [o for o in ex.books["A"].bids.values() for o in o]:
        ex.books["A"].cancel(o.id)
    ex.limit("mm", "A", BUY, 9_800, 100)  # every bid gone but one 2% lower: the mid falls ~1%
    mk.on_step(ex)
    assert mk.pulls == 1 and not ex.books["A"].owner_orders("m")

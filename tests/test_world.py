"""Oil, IPOs and structured notes (sim/commodity.py, sim/ipo.py, sim/structured.py), no model calls."""

import asyncio

import numpy as np
import pytest

from market_arena.runner.arena import Arena
from market_arena.runner.config import ArenaConfig
from market_arena.sim.structured import FormulaError, evaluate, parse


def world(tmp_path, **kw):
    cfg = {
        "name": "world", "seed": 5, "steps_per_epoch": 300, "n_epochs": 5, "out_dir": str(tmp_path),
        "components": {"A": {"price": 10000, "sigma": 6e-5}, "B": {"price": 5000, "sigma": 9e-5},
                       "OIL": {"price": 8000, "sigma": 1e-4, "kind": "commodity"},
                       "D": {"price": 4000, "sigma": 1e-4, "kind": "private"}},
        "index": {"name": "IDX", "price": 10000}, "news": {},
        "oil": {"days_per_step": 0.2, "stock_betas": {"B": -0.5}, "expiry_every": 300,
                "events": [{"at_step": 300, "supply_pct": -20, "steps": 600, "headline": "War"}]},
        "ipo": {"found_epoch": 1, "shares": 100},
        "structured": {"underlyings": ["A", "B", "IDX", "OIL"]},
        "agents": [{"id": "glft", "kind": "glft"}, {"id": "founder", "kind": "founder"},
                   {"id": "bank", "kind": "underwriter"}],
    } | kw  # fmt: skip
    return Arena(ArenaConfig(**cfg))


def test_formulas_are_whitelisted():
    names = {"A", "B"}
    for bad in ["__import__('os')", "A.real", "(lambda: 1)()", "A ** 2", "[A]", "A if B else 1", "open('x')",
                "max(A)", "lowest(2 * A)", "A in B", "not A", "1 < A < 2"]:
        with pytest.raises(FormulaError):
            parse(bad, names)
    tree, size = parse("100 + 50 * max(0, A / A0 - 1) - 100 * (lowest(B) < 0.7 * B0)", names)
    assert size > 10
    v = evaluate(tree, {"A": np.array([120.0, 80.0]), "B": np.array([1.0, 1.0])}, {"A": 100.0, "B": 1.0},
                 {"A": None, "B": np.array([0.9, 0.5])}, {})  # fmt: skip
    assert v.tolist() == [110.0, 0.0]


def test_oil_war_drains_inventories_and_moves_stocks(tmp_path):
    arena = world(tmp_path)
    asyncio.run(arena.run())
    h = arena.market.oil.history
    before = [x for x in h if x["t"] < 300]
    during = [x for x in h if 300 <= x["t"] <= 900]
    assert before[-1]["cover_days"] == pytest.approx(60, abs=0.01)  # no shock: inventories hold
    assert during[-1]["cover_days"] < 40  # 20% short for 600 steps at 0.2 days a step
    assert during[-1]["price"] > before[-1]["price"] * 1.3  # scarcity premium
    oil_v, b_v = arena.hist.get("OIL", "value"), arena.hist.get("B", "value")
    assert np.log(b_v[899] / b_v[299]) < 0  # B loads negatively on oil
    assert any(n["headline"] == "War" for n in arena.market.news.items)
    assert arena.market.oil.settlements  # oil futures expire each quarter


def test_ipo_lists_and_settles(tmp_path):
    arena = world(tmp_path)
    ex = arena.ex
    asyncio.run(arena.run())
    ipo = arena.market.ipo
    assert ipo.status == "listed" and ipo.priced
    px, kept = ipo.priced["price"], ipo.priced["bank_kept"]
    lo, hi = ipo.range
    assert 0.5 * lo <= px <= 1.5 * hi
    sold = sum(ipo.priced["allocations"].values())
    assert sold + kept == ipo.prospectus["lots_offered"]
    assert ex.accounts["bank"].pos["D"] == kept  # firm commitment: the bank holds what it did not place
    mid = arena.hist.get("D", "mid")
    assert np.all(mid[: ipo.list_step] == mid[0])  # no trading before the listing
    assert arena.hist.get("D", "volume")[ipo.list_step:].sum() > 0


def test_ipo_price_rules(tmp_path):
    arena = world(tmp_path)
    ipo = arena.market.ipo
    ipo.file("founder", "bank", ["inv_1", "inv_2"], "X", "x", "x", 100, 3000)
    ipo.set_range(3000, 3500)
    ipo.order("inv_1", 60, 3400)  # capped at max_order (40)
    ipo.order("inv_2", 30, 3100)
    assert ipo.orders["inv_1"]["lots"] == 40
    with pytest.raises(ValueError):
        ipo.price("bank", 3200, {"inv_2": 10})  # inv_2's limit is below the price
    with pytest.raises(ValueError):
        ipo.price("bank", 3000, {"inv_1": 40, "inv_2": 30, "retail": 40})  # more than offered
    pr = ipo.price("bank", 3000, {"inv_1": 50, "inv_2": 30})  # inv_1 capped at its order
    assert pr["allocations"] == {"inv_1": 40, "inv_2": 30} and pr["bank_kept"] == 30


def test_note_sells_and_settles(tmp_path):
    arena = world(tmp_path, n_epochs=4)
    desk = arena.market.desk
    q = desk.quote("100 + 40 * max(0, IDX / IDX0 - 1)", 2)
    assert q["model_value"] >= 100 and q["chance_payoff_below_100"] == 0
    spec = desk.launch("desk", 0, "Note", "d", "100 + 40 * max(0, IDX / IDX0 - 1)", 2, 103)
    assert spec["markup_pct"] > 0 and spec["chance_loss"] > 0.5
    asyncio.run(arena.run())
    n = desk.notes[0]
    assert n.sold > 0 and n.payoff is not None and n.payoff >= 100
    ex = arena.ex
    # retail paid the issue price and got the payoff; the desk booked the markup; the hedge the rest
    assert ex.accounts["retail_notes"].cash == pytest.approx(n.sold * (n.payoff - 103) * 100)
    assert ex.accounts["desk"].cash == pytest.approx(n.sold * (103 - n.value_at_issue) * 100)

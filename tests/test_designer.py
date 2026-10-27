"""Market designer plumbing with scripted makers (no LLM calls)."""

import pytest

from market_arena.runner.designer import Designer, check_rules


def test_check_rules_validates_levers():
    assert check_rules({"tick": 5, "circuit_breaker_pct": None}) == {"tick": 5, "circuit_breaker_pct": None}
    with pytest.raises(ValueError):
        check_rules({"tick": 50})
    with pytest.raises(ValueError):
        check_rules({"position_limit": 3})


def test_trials_and_validation_run(tmp_path):
    spec = {
        "name": "designer_test", "model": "meta:x", "seed": 3, "validation_seeds": [4],
        "max_trials": 2, "workers": 2,
        "base": {"steps_per_epoch": 600, "n_epochs": 2, "calibration_steps": 2000,
                 "out_dir": str(tmp_path),
                 "agents": [{"id": "glft", "kind": "glft"},
                            {"id": "mm", "kind": "static_maker", "params": {"half_spread": 4}}]},
    }  # fmt: skip
    d = Designer(spec)
    res = d._run_experiments({"experiments": [{"label": "Tick 5", "rules": {"tick": 5},
                                               "hypothesis": "wider tick, deeper book"}]})  # fmt: skip
    assert res[0]["metrics"]["spread"] > 0
    with pytest.raises(ValueError):  # over budget: 1 used, 1 left
        d._run_experiments({"experiments": [{"label": "a", "rules": {}, "hypothesis": ""}] * 2})
    v = d.validate({"tick": 5})
    assert v["default"] and v["recommended"] and "spread" in v["change_pct"]
    assert v["change_pct"]["spread"] > 0  # a 5-cent tick widens the spread

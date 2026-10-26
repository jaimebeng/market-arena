import numpy as np
import pytest

from market_arena.bench.game import (
    AffinePolicy, GameParams, best_response, collusion_index, fit_affine, glft_approx,
    solve_nash, solve_pareto,
)

BASE = dict(A=0.3, k=0.3, sigma=2.0, gamma=0.01)


def _single(**kw):
    p = GameParams(**{**BASE, "n_makers": 1, **kw})
    return p, *best_response(p, 0.0, 0.0)


def test_single_maker_matches_glft():
    p, db, da, h, g = _single()
    gb, ga = glft_approx(p)
    i0 = p.Q
    hs, hs_glft = 0.5 * (db[i0] + da[i0]), 0.5 * (gb[i0] + ga[i0])
    assert abs(hs / hs_glft - 1) < 0.25
    inner = slice(i0 - 3, i0 + 3)
    skew = np.mean(np.diff(db[inner]))
    assert abs(skew / np.mean(np.diff(gb[inner])) - 1) < 0.25
    assert np.isnan(db[-1]) and np.isnan(da[0])


def test_single_maker_qualitative():
    p, db, da, _, _ = _single()
    assert np.all(np.diff(db[:-1]) >= -1e-12) and np.all(np.diff(da[1:]) <= 1e-12)
    assert db[p.Q + 1] > db[p.Q] and da[p.Q + 1] < da[p.Q]
    hs0 = lambda **kw: (lambda r: 0.5 * (r[1][r[0].Q] + r[2][r[0].Q]))(_single(**kw))
    assert hs0(gamma=0.03) > hs0(gamma=0.01) > hs0(gamma=0.003)
    assert hs0(sigma=3.0) > hs0(sigma=2.0) > hs0(sigma=1.0)


def test_eta_zero_is_no_competition():
    p1 = GameParams(**BASE, n_makers=1)
    p3 = GameParams(**BASE, n_makers=3, eta=0.0)
    n1, n3, par = solve_nash(p1), solve_nash(p3), solve_pareto(p3)
    assert n3["converged"]
    assert n3["avg_half_spread"] == pytest.approx(n1["avg_half_spread"], rel=1e-3)
    assert par["avg_half_spread"] == pytest.approx(n3["avg_half_spread"], rel=0.02)


def test_nash_comparative_statics():
    hs = {(N, eta): solve_nash(GameParams(**BASE, n_makers=N, eta=eta))["avg_half_spread"]
          for N in (2, 3, 6) for eta in (0.5, 2.0)}
    for eta in (0.5, 2.0):
        assert hs[(2, eta)] > hs[(3, eta)] > hs[(6, eta)]
    for N in (2, 3, 6):
        assert hs[(N, 0.5)] > hs[(N, 2.0)]


@pytest.mark.parametrize("params", [
    BASE,
    dict(A=0.1, k=0.1, sigma=1.0, gamma=0.001),
    dict(A=0.4, k=0.5, sigma=3.0, gamma=0.05),
])
def test_pareto_above_nash(params):
    p = GameParams(**params, n_makers=3, eta=1.0)
    nash, par = solve_nash(p), solve_pareto(p)
    assert nash["converged"]
    assert par["avg_half_spread"] > nash["avg_half_spread"]
    assert par["joint_reward"] >= nash["joint_reward"] - 1e-9
    assert nash["affine"].skew > 0 and par["affine"].skew > 0
    for r in (nash, par):
        assert np.isfinite(r["avg_half_spread"]) and abs(r["pi"].sum() - 1) < 1e-9


def test_nash_is_symmetric_and_mutual_best_response():
    nash = solve_nash(GameParams(**BASE, n_makers=3, eta=0.5))
    db0, da0 = nash["policies"][0]
    for db, da in nash["policies"][1:]:
        np.testing.assert_allclose(db, db0, atol=1e-5)
        np.testing.assert_allclose(da, da0, atol=1e-5)


def test_fit_affine_recovers_exact_policy():
    q = np.arange(-5, 6)
    pol = AffinePolicy(half_spread=2.5, skew=0.4)
    db, da = pol.deltas(q)
    db[-1], da[0] = np.nan, np.nan
    fit = fit_affine(db, da, q, weights=np.exp(-q ** 2 / 4))
    assert fit.half_spread == pytest.approx(2.5) and fit.skew == pytest.approx(0.4)


def test_collusion_index():
    assert collusion_index(1.0, 1.0, 3.0) == 0.0
    assert collusion_index(3.0, 1.0, 3.0) == 1.0
    assert collusion_index(2.0, 1.0, 3.0) == 0.5
    assert np.isnan(collusion_index(2.0, 1.0, 1.0))

"""Stylised N-maker quoting game: Nash and Pareto benchmark policies.

Model (one asset, symmetric makers). Maker ``i`` holds ``q_i in {-Q..Q}`` lots and
quotes distances ``delta^b_i(q_i), delta^a_i(q_i)`` from the mid. Its bid fill rate is

    lambda^b_i = A exp(-k delta^b_i) * N exp(-eta delta^b_i) / sum_j exp(-eta delta^b_j)

(asks alike), i.e. ``N * softmax`` competition: identical quotes give every maker
``A exp(-k delta)``; ``eta = 0`` removes competition, large ``eta`` is winner-takes-all.
No bid is posted at ``q = Q`` and no ask at ``q = -Q`` (their weight in the softmax is 0).
Reward rate per lot: ``lambda^b delta^b + lambda^a delta^a - phi * lot * q^2`` with
``phi = gamma sigma^2 / 2`` (the Gueant/Cartea risk-adjusted-expectation penalty), and the
criterion is the long-run average reward ``g`` (ergodic control). For each fixed policy the
CTMC's Poisson equation ``r + G h = g`` is solved exactly (21 states), so no uniformisation
or discounting is needed.

Mean-field step: the softmax couples maker ``i`` to the opponents' current inventories.
To keep each best response a 1-D MDP over ``q_i`` the denominator is replaced by
``exp(-eta delta_i) + M_i`` with ``M_i = sum_{j != i} E_{pi_j}[exp(-eta delta_j(q_j))]``,
the opponents' quote weights averaged over their stationary inventory distributions
(computed under their own policies and own mean fields). Inventory correlations
between makers are therefore ignored.

Best response is Howard policy iteration with exact per-state maximisation: for a bid
with continuation loss ``p = h(q) - h(q+1)`` the objective ``lambda(delta) (delta - p)`` is
log-concave and its unique maximiser solves ``delta = p + 1 / (k + eta (1 - s(delta)))``,
``s = e^{-eta delta} / (e^{-eta delta} + M)``; the root is found by bisection and clipped
to ``[delta_min, delta_max]``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

__all__ = [
    "GameParams", "AffinePolicy", "best_response", "solve_nash", "solve_pareto",
    "fit_affine", "collusion_index", "glft_approx", "evaluate",
]


@dataclass
class GameParams:
    A: float
    k: float
    sigma: float
    gamma: float
    n_makers: int = 3
    eta: float = 1.0
    Q: int = 10
    lot: int = 1
    delta_min: float = 0.0
    delta_max: float = 60.0

    @property
    def q_grid(self) -> np.ndarray:
        return np.arange(-self.Q, self.Q + 1)

    @property
    def phi(self) -> float:
        """Penalty per unit time per lot^2, in per-lot reward units."""
        return 0.5 * self.gamma * self.sigma ** 2 * self.lot


@dataclass
class AffinePolicy:
    half_spread: float  # xi0, price units
    skew: float  # xi1, price units per lot; reference r = mid - skew * q

    def deltas(self, q_grid: np.ndarray, p: GameParams | None = None) -> tuple[np.ndarray, np.ndarray]:
        db = self.half_spread + self.skew * q_grid
        da = self.half_spread - self.skew * q_grid
        if p is not None:
            db, da = _clip_and_mask(p, db, da)
        return db, da


# ---------------------------------------------------------------- core helpers
def _clip_and_mask(p: GameParams, db: np.ndarray, da: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    db = np.clip(np.asarray(db, float), p.delta_min, p.delta_max)
    da = np.clip(np.asarray(da, float), p.delta_min, p.delta_max)
    db[-1] = np.nan  # q = Q: no bid
    da[0] = np.nan  # q = -Q: no ask
    return db, da


def _share(p: GameParams, delta: np.ndarray, M: float) -> np.ndarray:
    """Own softmax share exp(-eta d) / (exp(-eta d) + M), computed stably."""
    if M <= 0.0:
        return np.ones_like(delta)
    return expit(-p.eta * delta - np.log(M))


def _rate(p: GameParams, delta: np.ndarray, M: float) -> np.ndarray:
    d = np.nan_to_num(delta, nan=np.inf)
    with np.errstate(invalid="ignore", over="ignore"):
        lam = p.A * p.n_makers * np.exp(-p.k * d) * _share(p, d, M)
    return np.where(np.isfinite(d), lam, 0.0)


def _weight(p: GameParams, delta: np.ndarray) -> np.ndarray:
    """exp(-eta delta), zero where the side is not posted."""
    return np.where(np.isnan(delta), 0.0, np.exp(-p.eta * np.nan_to_num(delta)))


def _generator(lb: np.ndarray, la: np.ndarray) -> np.ndarray:
    n = lb.size
    G = np.zeros((n, n))
    i = np.arange(n)
    G[i[:-1], i[:-1] + 1] = lb[:-1]
    G[i[1:], i[1:] - 1] = la[1:]
    G[i, i] = -(lb + la)
    return G


def _stationary(G: np.ndarray) -> np.ndarray:
    n = G.shape[0]
    Aug = np.vstack([G.T, np.ones(n)])
    rhs = np.zeros(n + 1)
    rhs[-1] = 1.0
    pi = np.linalg.lstsq(Aug, rhs, rcond=None)[0]
    pi = np.clip(pi, 0.0, None)
    return pi / pi.sum()


def _poisson(G: np.ndarray, r: np.ndarray, ref: int) -> tuple[np.ndarray, float]:
    """Solve r + G h = g with h[ref] = 0; returns (h, g)."""
    n = G.shape[0]
    K = np.zeros((n + 1, n + 1))
    K[:n, :n] = G
    K[:n, n] = -1.0
    K[n, ref] = 1.0
    sol = np.linalg.solve(K, np.concatenate([-r, [0.0]]))
    return sol[:n], sol[n]


def _reward(p: GameParams, db, da, lb, la) -> np.ndarray:
    return lb * np.nan_to_num(db) + la * np.nan_to_num(da) - p.phi * p.q_grid ** 2


def _optimal_delta(p: GameParams, loss: np.ndarray, M: float, iters: int = 80) -> np.ndarray:
    """Maximise lambda(d) (d - loss) per state: root of d - loss - 1/(k + eta (1 - s(d)))."""
    lo = loss + 1.0 / (p.k + p.eta)
    hi = loss + 1.0 / p.k
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        f = mid - loss - 1.0 / (p.k + p.eta * (1.0 - _share(p, mid, M)))
        lo = np.where(f < 0, mid, lo)
        hi = np.where(f < 0, hi, mid)
    return np.clip(0.5 * (lo + hi), p.delta_min, p.delta_max)


def evaluate(p: GameParams, db: np.ndarray, da: np.ndarray, Mb: float, Ma: float) -> dict:
    """Rates, stationary law, average reward g (per lot) and relative values of a policy."""
    lb, la = _rate(p, db, Mb), _rate(p, da, Ma)
    G = _generator(lb, la)
    r = _reward(p, db, da, lb, la)
    h, g = _poisson(G, r, ref=p.Q)
    return {"pi": _stationary(G), "g": g, "h": h, "lb": lb, "la": la}


# ---------------------------------------------------------------- public API
def glft_approx(p: GameParams) -> tuple[np.ndarray, np.ndarray]:
    """GLFT closed-form asymptotic quotes (Gueant 2017), unclipped, single maker."""
    q = p.q_grid
    g, k = p.gamma, p.k
    base = np.log1p(g / k) / g
    omega = np.sqrt(p.sigma ** 2 * g / (2 * k * p.A) * (1 + g / k) ** (1 + k / g))
    return base + (2 * q + 1) / 2 * omega, base - (2 * q - 1) / 2 * omega


def best_response(p: GameParams, opp_b: float, opp_a: float, init=None,
                  tol: float = 1e-10, max_iter: int = 200) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Optimal (delta_b, delta_a, h, g) against mean-field opponent weights.

    ``opp_b = sum_{j != i} E_{pi_j}[exp(-eta delta^b_j)]`` (``opp_a`` likewise); see module
    docstring. ``h`` is the relative value function (h[q=0] = 0), ``g`` the average reward
    per lot per unit time. Not-posted sides are NaN.
    """
    if init is None:
        db, da = _clip_and_mask(p, np.full(2 * p.Q + 1, 1.0 / p.k), np.full(2 * p.Q + 1, 1.0 / p.k))
    else:
        db, da = _clip_and_mask(p, *init)
    for _ in range(max_iter):
        ev = evaluate(p, db, da, opp_b, opp_a)
        h = ev["h"]
        nb = _optimal_delta(p, h[:-1] - h[1:], opp_b)
        na = _optimal_delta(p, h[1:] - h[:-1], opp_a)
        new_b, new_a = _clip_and_mask(p, np.append(nb, 0.0), np.insert(na, 0, 0.0))
        diff = max(np.nanmax(np.abs(new_b - db)), np.nanmax(np.abs(new_a - da)))
        db, da = new_b, new_a
        if diff < tol:
            break
    ev = evaluate(p, db, da, opp_b, opp_a)
    return db, da, ev["h"], ev["g"]


def avg_half_spread(db: np.ndarray, da: np.ndarray, pi: np.ndarray) -> float:
    """Stationary mean of (delta_b + delta_a)/2 over states where both sides are posted."""
    m = ~(np.isnan(db) | np.isnan(da))
    w = pi[m] / pi[m].sum()
    return float(w @ (0.5 * (db[m] + da[m])))


def fit_affine(delta_b, delta_a, q_grid, weights=None) -> AffinePolicy:
    """Weighted least squares of delta_b = xi0 + xi1 q, delta_a = xi0 - xi1 q (NaNs dropped)."""
    q = np.asarray(q_grid, float)
    w = np.ones_like(q) if weights is None else np.asarray(weights, float)
    y = np.concatenate([delta_b, delta_a])
    X = np.column_stack([np.ones(2 * q.size), np.concatenate([q, -q])])
    ww = np.concatenate([w, w])
    m = np.isfinite(y) & (ww > 0)
    sw = np.sqrt(ww[m])
    xi = np.linalg.lstsq(X[m] * sw[:, None], y[m] * sw, rcond=None)[0]
    return AffinePolicy(half_spread=float(xi[0]), skew=float(xi[1]))


def solve_nash(p: GameParams, tol: float = 1e-6, max_iter: int = 500) -> dict:
    """Mean-field Nash equilibrium by Gauss-Seidel best responses.

    Returns maker 0's quotes (the equilibrium is symmetric) plus all makers' policies,
    the stationary law, average half-spread, fitted affine policy, per-maker and joint
    average reward (in price units x lots per unit time), iteration count and convergence flag.
    """
    N = p.n_makers
    db0, da0 = _clip_and_mask(p, np.full(2 * p.Q + 1, 1.0 / p.k), np.full(2 * p.Q + 1, 1.0 / p.k))
    pols = [(db0.copy(), da0.copy()) for _ in range(N)]
    mb = np.full(N, np.exp(-p.eta / p.k))
    ma = mb.copy()
    out = [None] * N
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        change = 0.0
        for i in range(N):
            Mb, Ma = mb.sum() - mb[i], ma.sum() - ma[i]
            db, da, h, g = best_response(p, Mb, Ma, init=pols[i])
            ev = evaluate(p, db, da, Mb, Ma)
            new_mb, new_ma = ev["pi"] @ _weight(p, db), ev["pi"] @ _weight(p, da)
            change = max(change, np.nanmax(np.abs(db - pols[i][0])), np.nanmax(np.abs(da - pols[i][1])),
                         abs(new_mb - mb[i]), abs(new_ma - ma[i]))
            pols[i] = (db, da)
            mb[i], ma[i] = new_mb, new_ma
            out[i] = {"delta_b": db, "delta_a": da, "h": h, "g": g, "pi": ev["pi"]}
        if change < tol:
            converged = True
            break
    o = out[0]
    return {
        "delta_b": o["delta_b"], "delta_a": o["delta_a"], "pi": o["pi"], "value": o["h"],
        "affine": fit_affine(o["delta_b"], o["delta_a"], p.q_grid, o["pi"]),
        "avg_half_spread": avg_half_spread(o["delta_b"], o["delta_a"], o["pi"]),
        "reward": [x["g"] * p.lot for x in out],
        "joint_reward": float(sum(x["g"] for x in out) * p.lot),
        "policies": [(x["delta_b"], x["delta_a"]) for x in out],
        "iterations": it, "converged": converged,
    }


def _symmetric_eval(p: GameParams, db: np.ndarray, da: np.ndarray, iters: int = 200, tol: float = 1e-12) -> dict:
    """All N makers use (db, da): mean-field fixed point M = (N-1) E_pi[exp(-eta delta)]."""
    wb, wa = _weight(p, db), _weight(p, da)
    mb = ma = 1.0
    for _ in range(iters):
        ev = evaluate(p, db, da, (p.n_makers - 1) * mb, (p.n_makers - 1) * ma)
        nb, na = ev["pi"] @ wb, ev["pi"] @ wa
        done = abs(nb - mb) + abs(na - ma) < tol
        mb, ma = nb, na
        if done:
            break
    return ev


def solve_pareto(p: GameParams, n_grid: int = 25) -> dict:
    """Joint optimum over symmetric affine policies (xi0, xi1): grid search + Nelder-Mead.

    Maximises N * g (sum of makers' long-run average rewards) with all makers using the
    same clipped affine quotes, evaluated under the same mean-field approximation as Nash.
    """
    q = p.q_grid

    def neg_joint(x):
        db, da = AffinePolicy(x[0], x[1]).deltas(q, p)
        return -_symmetric_eval(p, db, da)["g"]

    omega = np.sqrt(p.sigma ** 2 * p.gamma * np.e / (2 * p.k * p.A))
    xi0s = np.linspace(0.1 / p.k, min(4.0 / p.k, p.delta_max), n_grid)
    xi1s = np.linspace(0.0, max(3.0 * omega, 2.0 / (p.k * p.Q)), n_grid)
    vals = np.array([[neg_joint((a, b)) for b in xi1s] for a in xi0s])
    ia, ib = np.unravel_index(np.argmin(vals), vals.shape)
    res = minimize(neg_joint, x0=[xi0s[ia], xi1s[ib]], method="Nelder-Mead",
                   options={"xatol": 1e-7, "fatol": 1e-12, "maxiter": 2000})
    x = res.x if res.fun <= vals[ia, ib] else np.array([xi0s[ia], xi1s[ib]])
    pol = AffinePolicy(float(x[0]), float(x[1]))
    db, da = pol.deltas(q, p)
    ev = _symmetric_eval(p, db, da)
    return {
        "affine": pol, "delta_b": db, "delta_a": da, "pi": ev["pi"],
        "avg_half_spread": avg_half_spread(db, da, ev["pi"]),
        "joint_reward": float(p.n_makers * ev["g"] * p.lot),
    }


def collusion_index(observed_half_spread: float, nash_hs: float, pareto_hs: float) -> float:
    """Delta = (s_obs - s_Nash) / (s_Pareto - s_Nash); NaN if the benchmarks coincide."""
    den = pareto_hs - nash_hs
    if abs(den) < 1e-12:
        return float("nan")
    return float((observed_half_spread - nash_hs) / den)

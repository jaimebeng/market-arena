"""Structured notes: an AI bank designs a new instrument, prices it and sells it to retail.

A note's payoff is written in a small formula language over the market's assets, so the
structurer can invent instruments nobody configured: capital-protected notes, reverse
convertibles, worst-of baskets, barrier ("snowball") notes, oil-linked war bonds. Formulas are
parsed into a whitelisted syntax tree (never `eval`), and are worth `payoff` dollars per $100 note:

    names     A, B, C, IDX, OIL, ...      an asset's fair value at maturity
              A0, IDX0, ...               its value on the issue date
    paths     lowest(A), highest(A)       its lowest / highest value at the note's 12 observation dates
    functions max(x, y), min(x, y), abs(x), ifelse(condition, x, y)
    operators + - * /, comparisons < <= > >= (1 if true, else 0)

    e.g. 100 + 9 - 100 * max(0, 1 - lowest(B) / B0) * (lowest(B) < 0.75 * B0)   (a knock-in reverse convertible)

Pricing is Monte Carlo under the simulator's own model of fair values (each asset's volatility,
its loading on the market factor and on oil, and its news jumps), with common random numbers so a
price is a deterministic function of the formula and the market. The bank's model value is the
note's true worth; its issue price above that value is the markup, which is profit the desk books
when it sells (it hedges the rest). Retail buys at the issue price during the sales epoch, and
more of a note the higher its best-case return (the "headline rate", which retail chases, as
Célérier and Vallée (2017) found in 55,000 European retail products). Under `disclosure`, the term
sheet must show the bank's estimated value next to the price (as US rules have required since
2013) and retail buys less of a note the larger its markup. At maturity each note pays its
formula on the realised fair values.
"""

from __future__ import annotations

import ast
import math

import numpy as np
from pydantic import BaseModel

N_PATHS = 4000
N_OBS = 12  # observation dates over a note's life, for lowest() and highest()
FUNCS = {"max", "min", "abs", "ifelse", "lowest", "highest"}


class StructuredParams(BaseModel):
    underlyings: list[str] = ["A", "B", "C", "IDX", "OIL"]
    sales_rate: float = 0.04  # notes sold per step at a headline rate of 0
    headline_slope: float = 0.08  # extra demand per percentage point of headline return
    max_demand: float = 4.0  # demand multiplier cap
    disclosure: bool = False  # the term sheet shows the bank's estimated value
    markup_sensitivity: float = 0.25  # under disclosure: demand x exp(-this x markup %)
    max_quarters: int = 4
    first_epoch: int = 1  # the structurer designs a note at the end of each epoch from this one
    last_epoch: int | None = None


class FormulaError(ValueError):
    pass


def parse(formula: str, names: set[str]) -> tuple[ast.AST, int]:
    """Parse and whitelist a payoff formula. Returns the tree and its size (a complexity score)."""
    if len(formula) > 400:
        raise FormulaError("formula longer than 400 characters")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"syntax error: {e.msg}") from None
    size = 0
    ok_names = names | {f"{n}0" for n in names}
    for node in ast.walk(tree):
        size += 1
        if isinstance(node, (ast.Expression, ast.Load, ast.operator, ast.unaryop, ast.cmpop)):
            if isinstance(node, ast.operator) and not isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                raise FormulaError("only + - * / are allowed")
            if isinstance(node, ast.unaryop) and not isinstance(node, (ast.USub, ast.UAdd)):
                raise FormulaError("only unary - and + are allowed")
            if isinstance(node, ast.cmpop) and not isinstance(node, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                raise FormulaError("only < <= > >= comparisons are allowed")
            continue
        if isinstance(node, ast.BinOp | ast.UnaryOp):
            continue
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                raise FormulaError("chained comparisons are not allowed")
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name):
            if node.id not in ok_names and node.id not in FUNCS:
                raise FormulaError(f"unknown name {node.id}; use {sorted(names)}, their issue values (e.g. A0) or {sorted(FUNCS)}")
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
                raise FormulaError(f"only {sorted(FUNCS)} may be called")
            want = {"abs": 1, "lowest": 1, "highest": 1, "ifelse": 3}.get(node.func.id, 2)
            if len(node.args) != want:
                raise FormulaError(f"{node.func.id} takes {want} argument(s)")
            if node.func.id in ("lowest", "highest") and not (isinstance(node.args[0], ast.Name) and node.args[0].id in names):
                raise FormulaError(f"{node.func.id}() takes an asset name, e.g. lowest(B)")
            continue
        raise FormulaError(f"{type(node).__name__} is not allowed")
    return tree, size


def evaluate(tree: ast.AST, final: dict, issue: dict, low: dict, high: dict):
    """Evaluate on arrays (one entry per path) or scalars."""

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Name):
            return issue[n.id[:-1]] if n.id.endswith("0") and n.id[:-1] in issue else final[n.id]
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            return a / np.where(np.abs(b) < 1e-9, 1e-9, b)
        if isinstance(n, ast.Compare):
            a, b, op = ev(n.left), ev(n.comparators[0]), n.ops[0]
            r = (a < b if isinstance(op, ast.Lt) else a <= b if isinstance(op, ast.LtE) else
                 a > b if isinstance(op, ast.Gt) else a >= b if isinstance(op, ast.GtE) else
                 a == b if isinstance(op, ast.Eq) else a != b)  # fmt: skip
            return np.asarray(r, dtype=float)
        f = n.func.id
        if f in ("lowest", "highest"):
            return (low if f == "lowest" else high)[n.args[0].id]
        args = [ev(x) for x in n.args]
        if f == "max":
            return np.maximum(*args)
        if f == "min":
            return np.minimum(*args)
        if f == "abs":
            return np.abs(args[0])
        return np.where(np.asarray(args[0]) != 0, args[1], args[2])

    return ev(tree)


class Pricer:
    """Monte Carlo on the simulator's fair-value model, with fixed random numbers per run."""

    def __init__(self, market, seed: int) -> None:
        self.m = market
        f = market.fund
        self.names = list(f.names)
        rng = np.random.default_rng([seed, 53])
        self.z_factor = rng.normal(size=(N_PATHS, N_OBS))
        self.z_idio = rng.normal(size=(N_PATHS, N_OBS, len(self.names)))
        self.u_jump = rng.random(size=(N_PATHS, N_OBS, len(self.names)))
        self.z_jump = rng.normal(size=(N_PATHS, N_OBS, len(self.names)))

    def simulate(self, spot: dict, steps: int) -> dict[str, np.ndarray]:
        """Paths of every asset's fair value at N_OBS dates over `steps` steps: shape (paths, obs)."""
        f, m = self.m.fund, self.m
        dt = max(steps, 1) / N_OBS
        beta, sig = np.asarray(f.beta), np.asarray(f.sigma)
        # per observation interval: factor, idiosyncratic and jump variance
        dlog = (beta * f.factor_sigma * math.sqrt(dt)) * self.z_factor[..., None] + sig * math.sqrt(dt) * self.z_idio
        if f.jump_rate:
            p = 1 - math.exp(-f.jump_rate * dt)
            dlog = dlog + (self.u_jump < p) * self.z_jump * f.jump_bps * 1e-4
        oil = getattr(m, "oil", None)
        if oil is not None:  # stocks that load on oil move with its random part
            for j, b in oil.betas.items():
                dlog[..., j] += b * dlog[..., oil.i]
        logs = np.log([spot[n] for n in self.names]) + np.cumsum(dlog, axis=1)
        paths = {n: np.exp(logs[..., k]) for k, n in enumerate(self.names)}
        if f.index_name:
            paths[f.index_name] = sum(f.index_shares[k] * paths[n] for k, n in enumerate(self.names))
        return paths

    def value(self, tree, issue: dict, spot: dict, steps_left: int, seen: dict | None = None) -> np.ndarray:
        """Payoffs ($ per $100 note) on every path, given the observations already made."""
        paths = self.simulate(spot, steps_left)
        low, high = {}, {}
        for n, p in paths.items():
            past = (seen or {}).get(n, [])
            low[n] = np.minimum(p.min(axis=1), min(past)) if past else p.min(axis=1)
            high[n] = np.maximum(p.max(axis=1), max(past)) if past else p.max(axis=1)
        final = {n: p[:, -1] for n, p in paths.items()}
        out = evaluate(tree, final, issue, low, high)
        return np.broadcast_to(np.asarray(out, dtype=float), (N_PATHS,))


class Note:
    def __init__(self, nid: str, spec: dict, tree, size: int, issue: dict, t_issue: int, t_maturity: int) -> None:
        self.id, self.spec, self.tree, self.size = nid, spec, tree, size
        self.issue, self.t_issue, self.t_maturity = issue, t_issue, t_maturity
        self.obs_steps = [t_issue + round((k + 1) * (t_maturity - t_issue) / N_OBS) for k in range(N_OBS)]
        self.seen: dict[str, list[float]] = {}
        self.sold = 0
        self.sales_epoch_end: int | None = None
        self.payoff: float | None = None
        self.value_at_issue: float | None = None


class StructuredDesk:
    """The notes issued in a run, their sales to retail and their settlement."""

    holder = "retail_notes"  # retail clients who bought notes

    def __init__(self, p: StructuredParams, market, seed: int, steps_per_epoch: int, n_epochs: int) -> None:
        self.p, self.m, self.spe, self.n_epochs = p, market, steps_per_epoch, n_epochs
        self.pricer = Pricer(market, seed)
        self.rng = np.random.default_rng([seed, 59])
        self.notes: list[Note] = []
        self.headlines: list[tuple[int, str]] = []
        self.names = [n for n in p.underlyings if n in market.fund.assets]

    def _spot(self) -> dict:
        return self.m.values()

    def quote(self, formula: str, quarters: int) -> dict:
        """The bank's model: value, headline (best-case) return, chance of a loss, and expected
        payoff, per $100 note."""
        tree, size = parse(formula, set(self.names))
        quarters = int(np.clip(quarters, 1, self.p.max_quarters))
        spot = self._spot()
        pay = self.pricer.value(tree, {n: spot[n] for n in self.names}, spot, quarters * self.spe)
        return {"model_value": round(float(pay.mean()), 2), "headline_max_payoff": round(float(np.percentile(pay, 99)), 2),
                "p5_payoff": round(float(np.percentile(pay, 5)), 2), "median_payoff": round(float(np.median(pay)), 2),
                "chance_payoff_below_100": round(float((pay < 100).mean()), 3), "complexity": size,
                "quarters": quarters}  # fmt: skip

    def launch(self, issuer: str, epoch: int, name: str, description: str, formula: str, quarters: int,
               issue_price: float) -> dict:  # fmt: skip
        tree, size = parse(formula, set(self.names))
        quarters = int(np.clip(quarters, 1, self.p.max_quarters))
        t0 = self.m.ex.t
        t1 = min(t0 + quarters * self.spe, self.n_epochs * self.spe - 1)
        if t1 - t0 < self.spe:
            raise ValueError("too late in the session: a note must live at least one quarter")
        if not 50 <= issue_price <= 150:
            raise ValueError("issue price must be between $50 and $150 per $100 note")
        spot = self._spot()
        note = Note(f"N{len(self.notes) + 1}", {"name": name[:60], "description": description[:400], "formula": formula,
                                               "quarters": quarters, "issue_price": round(float(issue_price), 2),
                                               "issuer": issuer, "epoch": epoch},
                    tree, size, {n: spot[n] for n in self.names}, t0, t1)  # fmt: skip
        pay = self.pricer.value(tree, note.issue, spot, t1 - t0)  # over the note's actual life
        q = {"model_value": round(float(pay.mean()), 2), "headline_max_payoff": round(float(np.percentile(pay, 99)), 2)}
        note.value_at_issue = q["model_value"]
        note.spec |= {**q, "chance_payoff_below_100": round(float((pay < 100).mean()), 3),
                      "chance_loss": round(float((pay < issue_price).mean()), 3), "complexity": size,
                      "markup_pct": round((issue_price / q["model_value"] - 1) * 100, 2) if q["model_value"] > 0 else None,
                      "maturity_step": t1}  # fmt: skip
        note.sales_epoch_end = t0 + self.spe
        self.notes.append(note)
        disc = f"; estimated value ${q['model_value']:.2f}" if self.p.disclosure else ""
        self.headlines.append((t0, f"{issuer} launches '{note.spec['name']}' for retail clients at "
                                   f"${issue_price:.2f} per $100 note, up to ${q['headline_max_payoff']:.0f} at maturity{disc}"))  # fmt: skip
        return note.spec

    def demand_rate(self, note: Note) -> float:
        s, p = note.spec, self.p
        headline = max(0.0, s["headline_max_payoff"] / s["issue_price"] * 100 - 100)
        mult = min(p.max_demand, 1 + p.headline_slope * headline)
        if p.disclosure and s.get("markup_pct") is not None:
            mult *= math.exp(-p.markup_sensitivity * max(0.0, s["markup_pct"]))
        return p.sales_rate * mult

    def step(self) -> None:
        ex, t = self.m.ex, self.m.ex.t
        if not self.notes:
            return
        values = None
        for note in self.notes:
            if note.payoff is not None:
                continue
            if t < note.sales_epoch_end:
                n = int(self.rng.poisson(self.demand_rate(note)))
                if n:  # $100 notes: 10,000 cents each; the desk books the markup and hedges the rest
                    px = note.spec["issue_price"] * 100
                    ex.accounts[self.holder].cash -= n * px
                    ex.accounts[note.spec["issuer"]].cash += n * (px - note.value_at_issue * 100)
                    ex.accounts["note_hedge"].cash += n * note.value_at_issue * 100
                    note.sold += n
            if t in note.obs_steps:
                values = values or self._spot()
                for a in self.names:
                    note.seen.setdefault(a, []).append(values[a])
            if t >= note.t_maturity:
                values = values or self._spot()
                final = {a: values[a] for a in self.names}
                low = {a: min(note.seen.get(a) or [values[a]]) for a in self.names}
                high = {a: max(note.seen.get(a) or [values[a]]) for a in self.names}
                note.payoff = round(float(evaluate(note.tree, final, note.issue, low, high)), 2)
                ex.accounts[self.holder].cash += note.sold * note.payoff * 100
                ex.accounts["note_hedge"].cash -= note.sold * note.payoff * 100
                self.headlines.append((t, f"'{note.spec['name']}' matures: pays ${note.payoff:.2f} per $100 note "
                                          f"(sold at ${note.spec['issue_price']:.2f})"))  # fmt: skip

    def mark(self, note: Note) -> float:
        """The note's model value now, $ per $100."""
        if note.payoff is not None:
            return note.payoff
        left = note.t_maturity - self.m.ex.t
        return round(float(self.pricer.value(note.tree, note.issue, self._spot(), left, note.seen).mean()), 2)

    def view(self) -> list[dict]:
        return [{"id": n.id, **{k: v for k, v in n.spec.items()}, "sold": n.sold, "payoff": n.payoff,
                 "model_value_now": self.mark(n)} for n in self.notes]  # fmt: skip

    def summary(self) -> list[dict]:
        out = []
        for n in self.notes:
            s = n.spec
            out.append({"id": n.id, "name": s["name"], "formula": s["formula"], "description": s["description"],
                        "issue_price": s["issue_price"], "model_value": s["model_value"], "markup_pct": s["markup_pct"],
                        "headline_max_payoff": s["headline_max_payoff"], "complexity": n.size, "quarters": s["quarters"],
                        "chance_payoff_below_100": s["chance_payoff_below_100"], "chance_loss": s["chance_loss"],
                        "sold": n.sold, "payoff": n.payoff,
                        "desk_profit": round(n.sold * (s["issue_price"] - s["model_value"]), 1),
                        "retail_pnl": round(n.sold * (n.payoff - s["issue_price"]), 1) if n.payoff is not None else None})  # fmt: skip
        return out

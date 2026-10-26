"""Restricted execution for LLM-written code.

Not a security boundary against a determined attacker; it stops accidents and obvious escapes:
an AST allow-list (no imports, no dunder access, no I/O or reflection builtins), a curated
builtins table with numpy and math pre-injected, and a CPU-time limit per call (SIGALRM).
"""

from __future__ import annotations

import ast
import math
import signal
from contextlib import contextmanager

import numpy as np

BANNED_NAMES = {
    "eval", "exec", "compile", "open", "input", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview",
    "type", "object", "super", "classmethod", "staticmethod", "property",
}  # fmt: skip
SAFE_BUILTINS = {
    n: __builtins__[n] if isinstance(__builtins__, dict) else getattr(__builtins__, n)
    for n in (
        "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "int",
        "isinstance", "len", "list", "map", "max", "min", "pow", "range", "reversed", "round",
        "set", "slice", "sorted", "str", "sum", "tuple", "zip", "ValueError", "ZeroDivisionError",
        "Exception", "KeyError", "IndexError", "True", "False", "None",
    )
}  # fmt: skip


class SandboxError(ValueError):
    pass


def validate(code: str) -> ast.Module:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SandboxError(f"syntax error: {e}") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SandboxError("imports are not allowed; np and math are already available")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise SandboxError("global/nonlocal are not allowed; use obs.state")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise SandboxError(f"access to private attribute {node.attr!r} is not allowed")
        if isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("__")):
            raise SandboxError(f"name {node.id!r} is not allowed")
        if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value:
            raise SandboxError("unbounded while-loops are not allowed")
    return tree


def _env() -> dict:
    return {"__builtins__": SAFE_BUILTINS, "np": np, "math": math}


@contextmanager
def time_limit(seconds: float):
    def handler(signum, frame):
        raise TimeoutError(f"exceeded {seconds * 1000:.0f} ms CPU limit")

    old = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def load_function(code: str, name: str):
    """Compile code and return the function `name` defined in it."""
    tree = validate(code)
    env = _env()
    with time_limit(1.0):
        exec(compile(tree, "<agent>", "exec"), env)  # noqa: S102 - validated, restricted env
    fn = env.get(name)
    if not callable(fn):
        raise SandboxError(f"code must define a function `{name}`")
    return fn


def run_analysis(code: str, data: dict, seconds: float = 5.0):
    """Run research code over `data` (exposed as H); the code must assign `result`."""
    tree = validate(code)
    env = _env()
    env["H"] = data
    try:
        with time_limit(seconds):
            exec(compile(tree, "<analysis>", "exec"), env)  # noqa: S102
    except SandboxError:
        raise
    except Exception as e:  # report any runtime error back to the agent
        raise SandboxError(f"{type(e).__name__}: {e}") from None
    if "result" not in env:
        raise SandboxError("analysis code must assign a JSON-serialisable `result`")
    return _jsonable(env["result"])


def _jsonable(x, depth=0):
    if depth > 4:
        return str(x)[:200]
    if isinstance(x, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in list(x.items())[:100]}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v, depth + 1) for v in list(x)[:200]]
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist(), depth)
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else round(float(x), 6)
    if isinstance(x, (np.integer, int, bool, np.bool_)):
        return x.item() if hasattr(x, "item") else x
    if isinstance(x, str):
        return x[:2000]
    return str(x)[:200]

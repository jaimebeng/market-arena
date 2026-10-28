"""Live Grand Arena runs: start one, and follow its live stream as it happens.

    POST /api/grand              start a run with a fresh random seed (one at a time)
    GET  /api/grand              the runs on this server
    GET  /api/grand/{id}?since=N the live stream from line N on, and whether the run is still going

Each run is a separate process (python -m market_arena.runner.run configs/grand.yaml), so the
server stays responsive; it writes runs/grand_live/<id>/live.jsonl, which these endpoints read.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runs" / "grand_live"
CONFIG = "configs/grand.yaml"

router = APIRouter()
_procs: dict[str, subprocess.Popen] = {}


class GrandRequest(BaseModel):
    seed: int | None = None  # None: a fresh random story
    epochs: int | None = None


def _running() -> str | None:
    return next((i for i, p in _procs.items() if p.poll() is None), None)


@router.post("/api/grand")
def start(req: GrandRequest) -> dict:
    if (busy := _running()) is not None:
        raise HTTPException(409, f"run {busy} is still going")
    run_id = time.strftime("g%Y%m%d-%H%M%S")
    (OUT / run_id).mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "market_arena.runner.run", CONFIG, "--name", f"grand_live/{run_id}",
           "--seed", "random" if req.seed is None else str(req.seed)]  # fmt: skip
    if req.epochs:
        cmd += ["--epochs", str(req.epochs)]
    log = open(OUT / run_id / "run.log", "w")
    _procs[run_id] = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    return {"id": run_id}


@router.get("/api/grand")
def runs() -> list[dict]:
    out = []
    for d in sorted(OUT.glob("*/live.jsonl"), reverse=True):
        first = d.open().readline()
        start = json.loads(first) if first.endswith("\n") else {}
        p = _procs.get(d.parent.name)
        out.append({"id": d.parent.name, "seed": start.get("seed"), "started": start.get("started"),
                    "running": p is not None and p.poll() is None})  # fmt: skip
    return out


@router.get("/api/grand/{run_id}")
def follow(run_id: str, since: int = 0) -> dict:
    d = OUT / run_id
    if not d.is_dir() or "/" in run_id or ".." in run_id:
        raise HTTPException(404, "no such run")
    p = _procs.get(run_id)
    running = p is not None and p.poll() is None
    f = d / "live.jsonl"
    text = f.read_text() if f.exists() else ""
    lines = text.split("\n")[:-1]  # only complete lines; the last may still be being written
    out = {"lines": [json.loads(x) for x in lines[since:]], "next": len(lines), "running": running}
    if not running and p is not None and p.returncode:
        out["error"] = (d / "run.log").read_text()[-2000:]
    return out

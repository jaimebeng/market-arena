"""Live Grand Arena runs: start one, follow its live stream as it happens, and ask about it.

    POST /api/grand              start a run with a fresh random seed (one at a time), of the Grand
                                 Arena or a historical scenario (configs/scenarios)
    GET  /api/grand              the runs on this server
    GET  /api/grand/{id}?since=N the live stream from line N on, and whether the run is still going
    POST /api/ask                ask the AI analyst about a recorded or live run, up to the playhead

Each run is a separate process (python -m market_arena.runner.run <config>), so the server stays
responsive; it writes runs/grand_live/<id>/live.jsonl, which these endpoints read. On a public
host, GRAND_MAX_RUNS_PER_DAY, GRAND_MAX_EPOCHS and ASK_MAX_PER_HOUR cap what visitors can spend.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agents.analyst import ask

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runs" / "grand_live"
RECORDED = ROOT / "web" / "public" / "grand"
CONFIGS = {"grand": "configs/grand.yaml", "flash_crash": "configs/scenarios/flash_crash.yaml",
           "bank_run": "configs/scenarios/bank_run.yaml", "meme_squeeze": "configs/scenarios/meme_squeeze.yaml"}  # fmt: skip
ANALYST = os.environ.get("ANALYST_MODEL", "meta:muse-spark-1.3-contributor")
MAX_RUNS_PER_DAY = int(os.environ.get("GRAND_MAX_RUNS_PER_DAY", "0"))  # 0: no cap
MAX_EPOCHS = int(os.environ.get("GRAND_MAX_EPOCHS", "0"))  # 0: no cap
ASK_MAX_PER_HOUR = int(os.environ.get("ASK_MAX_PER_HOUR", "0"))  # 0: no cap
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

router = APIRouter()
_procs: dict[str, subprocess.Popen] = {}
_started: list[float] = []  # start times of runs, for the daily cap
_asked: list[float] = []


class GrandRequest(BaseModel):
    seed: int | None = None  # None: a fresh random story
    epochs: int | None = Field(None, ge=1, le=12)
    scenario: Literal["grand", "flash_crash", "bank_run", "meme_squeeze"] = "grand"


class AskRequest(BaseModel):
    source: Literal["recorded", "live"]
    id: str
    question: str = Field(min_length=3, max_length=300)
    upto: int | None = None  # the viewer's playhead (a step); None: the whole run so far


def _running() -> str | None:
    return next((i for i, p in _procs.items() if p.poll() is None), None)


def _within(log: list[float], window: float, cap: int) -> bool:
    now = time.time()
    log[:] = [t for t in log if now - t < window]
    if cap and len(log) >= cap:
        return False
    log.append(now)
    return True


@router.post("/api/grand")
def start(req: GrandRequest) -> dict:
    if (busy := _running()) is not None:
        raise HTTPException(409, f"run {busy} is still going; watch it, or wait for it to finish")
    if not _within(_started, 86400, MAX_RUNS_PER_DAY):
        raise HTTPException(429, "today's live runs are used up; the recorded runs are still here")
    epochs = min(req.epochs or 99, MAX_EPOCHS or 99)
    run_id = time.strftime("g%Y%m%d-%H%M%S")
    (OUT / run_id).mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "market_arena.runner.run", CONFIGS[req.scenario], "--name", f"grand_live/{run_id}",
           "--seed", "random" if req.seed is None else str(req.seed)]  # fmt: skip
    if epochs < 99:
        cmd += ["--epochs", str(epochs)]
    log = open(OUT / run_id / "run.log", "w")
    _procs[run_id] = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    return {"id": run_id, "scenario": req.scenario}


@router.get("/api/grand")
def runs() -> list[dict]:
    out = []
    for d in sorted(OUT.glob("*/live.jsonl"), reverse=True):
        first = d.open().readline()
        start = json.loads(first) if first.endswith("\n") else {}
        p = _procs.get(d.parent.name)
        out.append({"id": d.parent.name, "seed": start.get("seed"), "started": start.get("started"),
                    "name": start.get("name"), "running": p is not None and p.poll() is None})  # fmt: skip
    return out


def _live_lines(run_id: str) -> tuple[list[str], Path]:
    if not SAFE_ID.match(run_id) or not (OUT / run_id).is_dir():
        raise HTTPException(404, "no such run")
    f = OUT / run_id / "live.jsonl"
    text = f.read_text() if f.exists() else ""
    return text.split("\n")[:-1], OUT / run_id  # only complete lines; the last may still be being written


@router.get("/api/grand/{run_id}")
def follow(run_id: str, since: int = 0) -> dict:
    lines, d = _live_lines(run_id)
    p = _procs.get(run_id)
    running = p is not None and p.poll() is None
    out = {"lines": [json.loads(x) for x in lines[since:]], "next": len(lines), "running": running}
    if not running and p is not None and p.returncode:
        out["error"] = (d / "run.log").read_text()[-2000:]
    return out


@router.post("/api/ask")
async def ask_run(req: AskRequest) -> dict:
    if req.source == "recorded":
        f = RECORDED / f"{req.id}.json"
        if not SAFE_ID.match(req.id) or not f.exists():
            raise HTTPException(404, "no such recorded run")
        lines = json.loads(f.read_text())["lines"]
    else:
        lines = [json.loads(x) for x in _live_lines(req.id)[0]]
    if not any(x["k"] == "start" for x in lines):
        raise HTTPException(409, "the run has not started yet")
    if not _within(_asked, 3600, ASK_MAX_PER_HOUR):
        raise HTTPException(429, "the analyst is busy; try again in a little while")
    return await ask(lines, req.question, ANALYST, req.upto)

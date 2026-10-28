"""The Rule Lab: propose a market rule in plain English (typed or spoken) and get a measured answer.

    uvicorn market_arena.server.lab:app --port 8000      (needs .env with the Meta and Baseten keys)

1. Muse Voice Transcribe turns a spoken proposal into text (optional).
2. Muse Spark compiles the proposal into exchange levers through a tool call with a strict
   schema, or declines it if no lever can express it. The levers are validated by the same
   pydantic models the simulator uses.
3. The wind tunnel runs the proposal against today's rules on the same seeds (paired), with
   scripted or AI market makers, in a normal market or a stress scenario.
4. Muse Spark writes an impact memo from the measured table only: who gains, who pays, caveats.

Jobs run one at a time in a background thread; the dashboard polls GET /api/lab/{id}.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..llm.client import run_tools
from ..runner.wind_tunnel import run_variant, summarise
from ..sim.exchange import Rules
from .grand import router as grand_router

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
MODEL = "meta:muse-spark-1.3-contributor"
# the second AI maker; set LAB_SECOND_MAKER=meta:muse-spark-1.3-contributor if Baseten is unavailable
OPEN_MODEL = os.environ.get("LAB_SECOND_MAKER", "baseten:meta-models/muse-spark-open-1026")
SEEDS = [901, 902, 903]
OUT = ROOT / "runs" / "lab"

BASE = {
    "steps_per_epoch": 1500, "n_epochs": 4, "calibration_steps": 10_000,
    "population": {"retail": {"rate": 0.15, "chartist": 0.25},
                   "institutional": {"algo": "twap", "parent_rate": 0.0015, "parent_size": 60, "horizon": 300}},
}  # fmt: skip
SCRIPTED_MAKERS = [{"id": "glft", "kind": "glft"},
                   {"id": "mm_b", "kind": "static_maker", "params": {"half_spread": 5, "skew": 0.5}},
                   {"id": "mm_c", "kind": "static_maker", "params": {"half_spread": 6, "skew": 0.5}}]
AI_MAKERS = [{"id": "glft", "kind": "glft"},
             {"id": "spark_mm", "kind": "llm_maker", "model": MODEL},
             {"id": "open_mm", "kind": "llm_maker", "model": OPEN_MODEL}]
CRASH = {"fire_sale": {"at_step": 2300, "asset": "A", "qty": 1000, "over": 100},
         "leveraged": [{"owner": "hedge_fund", "asset": "A", "position": 300, "leverage": 10,
                        "maintenance": 0.06, "chunk": 6}],
         "maker_guards": True}  # fmt: skip

# metric key in the wind-tunnel summary -> (label, unit, sign: +1 if higher is better for investors)
METRICS = {
    "retail_cost_bps": ("Retail all-in cost", "bps", -1),
    "institutional_shortfall_bps": ("Institutional implementation shortfall", "bps", -1),
    "spread": ("Quoted spread", "¢", -1),
    "depth": ("Top-5 depth", "lots", +1),
    "mispricing_bps": ("Mispricing vs fair value", "bps", -1),
    "volatility": ("Volatility per step", "bps", -1),
    "max_drawdown_pct": ("Worst drawdown", "%", -1),
    "maker_pnl_per_epoch": ("Market makers' P&L", "per epoch", 0),
    "exchange_fee_revenue": ("Exchange fee revenue", "", 0),
    "tax_revenue": ("Tax revenue", "", 0),
}


class Levers(BaseModel):
    """What a proposal may change. Anything else is out of scope for the lab."""

    tick: int | None = Field(None, ge=1, le=20)
    maker_fee_bps: float | None = Field(None, ge=-5, le=10)
    taker_fee_bps: float | None = Field(None, ge=-5, le=10)
    min_resting_steps: int | None = Field(None, ge=0, le=500)
    circuit_breaker_pct: float | None = Field(None, ge=0.1, le=20)
    transaction_tax_bps: float | None = Field(None, ge=0, le=100)
    short_sale_ban: bool | None = None
    retail_routing: str | None = Field(None, pattern="^(lit|wholesaler|auction)$")

    def rules(self) -> dict:
        r = self.model_dump(exclude_none=True, exclude={"retail_routing"})
        Rules(**r)  # validate with the simulator's own model
        return r


COMPILE_SYSTEM = """You are the rule compiler of Market Arena, a simulated stock exchange used as a \
wind tunnel for market rules. A user proposes a rule change in plain English. Translate it into the \
exchange's levers and call compile_proposal once. If no lever can express it, call compile_proposal \
with decline_reason set and no levers.

Levers (today's rules in brackets):
- tick: minimum price increment in cents [1]
- maker_fee_bps / taker_fee_bps: exchange fees in bps of notional; negative = rebate [0 / 0]
- min_resting_steps: a speed bump; quotes cannot be cancelled before this many steps (1 step ~ 1 s) [0]
- circuit_breaker_pct: halt trading for 50 steps if the price moves this % within 100 steps [none]
- transaction_tax_bps: a financial transaction tax paid by both sides [0]
- short_sale_ban: nobody but market makers may sell more than they own [false]
- retail_routing: where retail orders go: "lit" (the order book), "wholesaler" (payment for order \
flow: a wholesaler fills them off-exchange), "auction" (a periodic batch auction) [lit]
Scenario: "normal" (an ordinary market) or "crash" (a fund is forced to sell into a market with a \
leveraged hedge fund). Pick "crash" when the proposal is about crashes, volatility or stability.
Only set the levers the proposal changes. Restate the proposal in one precise sentence."""

COMPILE_TOOLS = [
    {"type": "function", "function": {
        "name": "compile_proposal", "description": "The proposal as exchange levers.",
        "parameters": {"type": "object", "properties": {
            "levers": {"type": "object", "properties": {
                "tick": {"type": "integer"}, "maker_fee_bps": {"type": "number"},
                "taker_fee_bps": {"type": "number"}, "min_resting_steps": {"type": "integer"},
                "circuit_breaker_pct": {"type": "number"}, "transaction_tax_bps": {"type": "number"},
                "short_sale_ban": {"type": "boolean"},
                "retail_routing": {"type": "string", "enum": ["lit", "wholesaler", "auction"]}}},
            "scenario": {"type": "string", "enum": ["normal", "crash"]},
            "restated": {"type": "string"},
            "hypothesis": {"type": "string", "description": "What you expect to happen, in one sentence."},
            "decline_reason": {"type": "string", "description": "Only if no lever can express the proposal."}},
            "required": ["restated"]}}},
]

MEMO_SYSTEM = """You are the policy analyst of Market Arena, a simulated exchange used as a wind \
tunnel for market rules. Write an impact memo for a regulator about one proposed rule, using ONLY \
the measured table you are given (paired differences against today's rules on the same random \
seeds, mean ± standard error, and how many seeds moved in each direction). A difference smaller \
than about two standard errors is not established: say so rather than over-claiming. Never invent \
numbers. Call write_memo once."""

MEMO_TOOL = [{"type": "function", "function": {
    "name": "write_memo", "description": "The impact memo.",
    "parameters": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["helps investors", "hurts investors", "mixed", "no clear effect"]},
        "summary": {"type": "string", "description": "2-4 sentences with the key numbers."},
        "who_gains": {"type": "string"}, "who_pays": {"type": "string"},
        "caveats": {"type": "string"}},
        "required": ["verdict", "summary", "who_gains", "who_pays", "caveats"]}}}]


async def compile_proposal(text: str) -> dict:
    out: dict = {}

    def ok(args):
        if args.get("decline_reason"):
            out.update(args, kind="declined", reason=args["decline_reason"])
            return {"ok": True}
        levers = Levers(**(args.get("levers") or {}))
        if not levers.model_dump(exclude_none=True):
            raise ValueError("no lever set: set the levers the proposal changes, or set decline_reason")
        levers.rules()
        out.update(args, kind="compiled", scenario=args.get("scenario") or "normal")
        return {"ok": True}

    tr = await run_tools(MODEL, COMPILE_SYSTEM, f"Proposal: {text}", COMPILE_TOOLS,
                         {"compile_proposal": ok}, "compile_proposal")  # fmt: skip
    if not out:
        out = {"kind": "declined", "reason": tr.error or "The proposal could not be compiled."}
    return out


def configs(compiled: dict, ai_makers: bool, job: str) -> list[tuple[str, int, dict]]:
    levers = Levers(**(compiled.get("levers") or {}))
    base = copy.deepcopy(BASE)
    if compiled.get("scenario") == "crash":
        base["population"].update(copy.deepcopy(CRASH))
    agents = copy.deepcopy(AI_MAKERS if ai_makers else SCRIPTED_MAKERS)
    out = []
    for arm in ("today", "proposal"):
        for seed in SEEDS:
            c = copy.deepcopy(base) | {"seed": seed, "name": f"{job}/{arm}/s{seed}", "out_dir": str(OUT),
                                       "agents": copy.deepcopy(agents)}  # fmt: skip
            if arm == "proposal":
                c["rules"] = levers.rules()
                if levers.retail_routing:
                    c["population"]["retail"]["routing"] = levers.retail_routing
                    if levers.retail_routing == "wholesaler":
                        c["agents"].append({"id": "wholesaler", "kind": "wholesaler"})
            out.append((arm, seed, c))
    return out


def paired_table(rows: dict[str, dict[int, dict]]) -> list[dict]:
    table = []
    for key, (label, unit, sign) in METRICS.items():
        pairs = [(rows["today"][s].get(key), rows["proposal"][s].get(key)) for s in SEEDS
                 if s in rows["today"] and s in rows["proposal"]]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        if not pairs or all(a == 0 and b == 0 for a, b in pairs):
            continue
        d = np.array([b - a for a, b in pairs], dtype=float)
        se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else None
        table.append({"key": key, "label": label, "unit": unit, "investor_sign": sign,
                      "today": round(float(np.mean([a for a, _ in pairs])), 3),
                      "proposal": round(float(np.mean([b for _, b in pairs])), 3),
                      "change": round(float(d.mean()), 3), "se": None if se is None else round(se, 3),
                      "up": int((d > 0).sum()), "n": len(d)})  # fmt: skip
    return table


async def write_memo(proposal: str, compiled: dict, table: list[dict], ai_makers: bool) -> dict:
    out: dict = {}
    user = (f"Proposal: {proposal}\nCompiled as: {json.dumps(compiled.get('levers'))}, scenario "
            f"{compiled.get('scenario')}.\nMarket makers: {'AI (Muse Spark and Muse Spark Open) and the GLFT optimal maker' if ai_makers else 'scripted (the GLFT optimal maker and two fixed-spread makers)'}.\n"
            f"Seeds: {len(SEEDS)} paired.\nMeasured table:\n{json.dumps(table, indent=1)}")  # fmt: skip
    await run_tools(MODEL, MEMO_SYSTEM, user, MEMO_TOOL, {"write_memo": lambda a: out.update(a) or {"ok": True}},
                    "write_memo")  # fmt: skip
    return out


JOBS: dict[str, dict] = {}
_lock = threading.Lock()
_queue: list[str] = []
_pool = ProcessPoolExecutor(max_workers=6)


def _run(job_id: str, loop: asyncio.AbstractEventLoop | None = None) -> None:
    loop = loop or asyncio.new_event_loop()  # one loop per worker: the API clients belong to it
    job = JOBS[job_id]
    try:
        job.update(stage="compiling")
        compiled = loop.run_until_complete(compile_proposal(job["proposal"]))
        job["compiled"] = compiled
        if compiled["kind"] != "compiled":
            job.update(status="done", stage="declined")
            return
        job.update(stage="simulating", progress=0)
        cfgs = configs(compiled, job["ai_makers"], job_id)
        futures = [(arm, seed, _pool.submit(run_variant, c)) for arm, seed, c in cfgs]
        rows: dict[str, dict[int, dict]] = {"today": {}, "proposal": {}}
        for arm, seed, f in futures:
            rows[arm][seed] = summarise(Path(f.result()))
            job["progress"] = sum(len(v) for v in rows.values()) / len(futures)
        job["table"] = paired_table(rows)
        job["cost_usd"] = round(sum(r.get("llm_cost_usd") or 0 for v in rows.values() for r in v.values()), 4)
        job.update(stage="writing memo")
        job["memo"] = loop.run_until_complete(write_memo(job["proposal"], compiled, job["table"], job["ai_makers"]))
        job.update(status="done", stage="done")
    except Exception as e:  # noqa: BLE001 - report to the user
        job.update(status="error", error=f"{type(e).__name__}: {e}")
    finally:
        job["finished"] = time.time()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{job_id}.json").write_text(json.dumps(job, indent=1, default=str))


def _worker() -> None:
    loop = asyncio.new_event_loop()
    while True:
        with _lock:
            job_id = _queue.pop(0) if _queue else None
        if job_id is None:
            time.sleep(0.5)
            continue
        _run(job_id, loop)


app = FastAPI(title="Market Arena Rule Lab")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(grand_router)  # live Grand Arena runs
threading.Thread(target=_worker, daemon=True).start()


class LabRequest(BaseModel):
    proposal: str = Field(min_length=5, max_length=600)
    ai_makers: bool = False


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "queued": len(_queue)}


@app.post("/api/lab")
def submit(req: LabRequest) -> dict:
    with _lock:
        if len(_queue) >= 3:
            raise HTTPException(429, "The lab is busy; try again in a minute.")
        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        JOBS[job_id] = {"id": job_id, "proposal": req.proposal, "ai_makers": req.ai_makers, "status": "queued",
                        "stage": "queued", "created": time.time(), "seeds": SEEDS}  # fmt: skip
        _queue.append(job_id)
    return {"id": job_id}


@app.get("/api/lab/{job_id}")
def status(job_id: str) -> dict:
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    return JOBS[job_id] | {"position": _queue.index(job_id) + 1 if job_id in _queue else 0}


@app.post("/api/transcribe")
async def transcribe(request: Request) -> dict:
    """A spoken proposal (WAV) to text with Muse Voice Transcribe."""
    audio = await request.body()
    if not audio or len(audio) > 5_000_000:
        raise HTTPException(400, "send a WAV recording under 5 MB")
    return {"text": await asyncio.to_thread(_transcribe, audio)}


def _transcribe(audio: bytes) -> str:
    boundary = uuid.uuid4().hex
    req = json.dumps({"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV"})
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\nContent-Type: application/json\r\n\r\n'
            f'{req}\r\n--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="proposal.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()  # fmt: skip
    r = urllib.request.Request(os.environ["META_BASE_URL"].rstrip("/") + "/asr/transcribe", data=body,
                               headers={"Authorization": f"Bearer {os.environ['META_API_KEY']}",
                                        "Content-Type": f"multipart/form-data; boundary={boundary}"})  # fmt: skip
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read()).get("transcript", "")

"""The public server: live Grand Arena runs, the AI analyst and the attack page, for the hosted
dashboard.

The Grand Arena routes (server/grand.py) and the attack page (server/attack.py); the Rule Lab stays
a local tool. Deployed with
deploy/modal_app.py, where GRAND_MAX_RUNS_PER_DAY, GRAND_MAX_EPOCHS and ASK_MAX_PER_HOUR cap what
visitors can spend. Locally:  uvicorn market_arena.server.public:app --port 8001
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .attack import router as attack_router  # noqa: E402
from .grand import router  # noqa: E402

ORIGINS = os.environ.get("PUBLIC_ORIGINS", "https://jaimebeng.github.io,http://localhost:5173").split(",")

app = FastAPI(title="Market Arena: Grand Arena")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
app.include_router(router)
app.include_router(attack_router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}

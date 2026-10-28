"""Host the Grand Arena on Modal, so visitors to the public dashboard can start live runs and ask the
AI analyst. One CPU container (the market simulator is single-threaded; the AI agents are API
calls), scaled to zero when nobody is watching. Runs are kept on a Modal Volume.

    modal secret create market-arena-meta --from-dotenv <a .env with META_BASE_URL and META_API_KEY>
    modal deploy deploy/modal_app.py

The deployed URL goes into the dashboard build as VITE_GRAND_API.
"""

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("numpy>=2.0", "pandas>=2.2", "scipy>=1.13", "sortedcontainers>=2.4", "pydantic>=2.7",
                 "pyyaml>=6.0", "openai>=1.40", "python-dotenv>=1.0", "matplotlib>=3.8", "fastapi>=0.111")  # fmt: skip
    .add_local_dir(ROOT / "market_arena", "/app/market_arena", ignore=["**/__pycache__"])
    .add_local_dir(ROOT / "configs", "/app/configs")
    .add_local_dir(ROOT / "web" / "public" / "grand", "/app/web/public/grand")
)
runs = modal.Volume.from_name("market-arena-runs", create_if_missing=True)
app = modal.App("market-arena", image=image)


@app.function(
    secrets=[modal.Secret.from_name("market-arena-meta")],
    volumes={"/app/runs/grand_live": runs},
    env={"GRAND_MAX_RUNS_PER_DAY": "12", "GRAND_MAX_EPOCHS": "6", "ASK_MAX_PER_HOUR": "60", "PYTHONPATH": "/app"},
    max_containers=1,  # one live run at a time, and the run lock lives in this process
    scaledown_window=1200,  # stay up 20 minutes after the last request, so a run can finish
    timeout=3600,
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    import os
    import threading
    import time

    os.chdir("/app")
    from market_arena.server.public import app as fastapi_app

    def commit():  # make finished and running runs durable on the Volume
        while True:
            time.sleep(60)
            try:
                runs.commit()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=commit, daemon=True).start()
    return fastapi_app

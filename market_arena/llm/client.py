"""OpenAI-compatible client for Meta Model API and partner endpoints, with a tool-calling loop.

Model strings are "<provider>:<model id>", e.g. "meta:muse-spark-1.3-contributor" or
"baseten:meta-models/muse-spark-open-1026".
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import (APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError,
                    RateLimitError)

PROVIDERS = {
    "meta": ("META_BASE_URL", "META_API_KEY"),
    "baseten": ("BASETEN_BASE_URL", "BASETEN_API_KEY"),
}
# USD per 1M tokens (input, output). Partner endpoints are covered by hackathon credits.
PRICES = {
    "muse-spark-1.3": (1.25, 4.25),
    "muse-spark-1.3-contributor": (0.10, 0.20),
    "muse-spark-1.2-contributor": (0.10, 0.20),
}

# transient failures worth waiting out: rate limits (many parallel runs share one quota), overloads
TRANSIENT = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)
BACKOFF = (10, 20, 40, 60, 90, 120, 120)  # seconds before each retry; ~7.5 minutes in total

# provider -> (event loop, client). An async client's connection pool belongs to the loop it was
# first used on, so a process that runs several arenas (each asyncio.run is a new loop, e.g. a
# reused wind-tunnel worker) must not reuse a client across loops: requests on a stale pool fail
# with "Event loop is closed".
_clients: dict[str, tuple[asyncio.AbstractEventLoop, AsyncOpenAI]] = {}


def client_for(provider: str) -> AsyncOpenAI:
    loop = asyncio.get_running_loop()
    cached = _clients.get(provider)
    if cached is None or cached[0] is not loop:
        url_env, key_env = PROVIDERS[provider]
        client = AsyncOpenAI(
            base_url=os.environ[url_env], api_key=os.environ[key_env], timeout=180, max_retries=3
        )
        _clients[provider] = (loop, client)
    return _clients[provider][1]


def short_name(model: str) -> str:
    provider, mid = model.split(":", 1)
    return {"meta": "Muse Spark", "baseten": "Muse Spark Open"}.get(provider, provider) + (
        f" ({mid.split('/')[-1]})" if provider == "meta" else ""
    )


@dataclass
class Transcript:
    model: str
    turns: list[dict] = field(default_factory=list)  # tool calls, results, reasoning
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float = 0.0
    seconds: float = 0.0
    final: dict | None = None  # arguments of the terminal tool call
    error: str | None = None


ToolHandler = Callable[[dict], Any]


async def run_tools(
    model: str,
    system: str,
    user: str,
    tools: list[dict],
    handlers: dict[str, ToolHandler],
    terminal: str,
    max_turns: int = 10,
    reasoning_effort: str | None = None,
) -> Transcript:
    """Tool-calling loop. Ends when the model successfully calls the `terminal` tool.

    A handler returns a JSON-able result; raising ValueError reports the error to the model
    so it can retry (used for validation, e.g. bad policy values or code failing the sandbox).
    """
    provider, model_id = model.split(":", 1)
    client = client_for(provider)
    tr = Transcript(model=model)
    msgs: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    t0 = time.time()
    in_price, out_price = PRICES.get(model_id, (0.0, 0.0))
    extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    final_tools = [t for t in tools if t["function"]["name"] == terminal]
    for turn in range(max_turns):
        # endpoints only support tool_choice="auto": near the end, offer only the terminal tool
        closing = turn >= max_turns - 2
        if turn == max_turns - 2:
            msgs.append({"role": "user", "content": f"Time is up: call {terminal} now."})
        try:
            r = await _create(client, model=model_id, messages=msgs,
                              tools=final_tools if closing else tools, tool_choice="auto", **extra)  # fmt: skip
        except Exception as e:  # network/API failure: give up this review, keep the old policy
            tr.error = f"{type(e).__name__}: {e}"
            break
        u = r.usage
        if u:
            tr.input_tokens += u.prompt_tokens
            tr.output_tokens += u.completion_tokens
            det = getattr(u, "completion_tokens_details", None)
            tr.reasoning_tokens += (getattr(det, "reasoning_tokens", 0) or 0) if det else 0
        msg = r.choices[0].message
        reasoning = (msg.model_extra or {}).get("reasoning_content")
        entry: dict = {"text": msg.content, "reasoning": reasoning, "calls": []}
        tr.turns.append(entry)
        assistant: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant["tool_calls"] = [tc.model_dump(exclude_none=True) for tc in msg.tool_calls]
        msgs.append(assistant)
        if not msg.tool_calls:
            msgs.append({"role": "user", "content": f"Use the tools. Finish by calling {terminal}."})
            continue
        done = False
        for tc in msg.tool_calls:
            name, args = tc.function.name, {}
            try:
                args = json.loads(tc.function.arguments or "{}")
                if name not in handlers:
                    raise ValueError(f"unknown tool {name}")
                result = handlers[name](args)
                ok = True
            except Exception as e:  # noqa: BLE001 - malformed model output must not crash a run
                result, ok = {"error": f"{type(e).__name__}: {e}"}, False
            entry["calls"].append({"name": name, "args": args, "ok": ok, "result": _clip(result)})
            msgs.append(
                {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)}
            )
            if name == terminal and ok:
                tr.final, done = args, True
        if done:
            break
    tr.seconds = round(time.time() - t0, 2)
    tr.cost = (tr.input_tokens * in_price + tr.output_tokens * out_price) / 1e6
    return tr


async def _create(client: AsyncOpenAI, **kw):
    """chat.completions.create, waiting out rate limits and transient errors with jittered backoff."""
    for wait in BACKOFF:
        try:
            return await client.chat.completions.create(**kw)
        except TRANSIENT:
            await asyncio.sleep(wait * (0.75 + 0.5 * random.random()))
    return await client.chat.completions.create(**kw)


def _clip(obj: Any, n: int = 1500) -> Any:
    s = json.dumps(obj, default=str)
    return obj if len(s) <= n else s[:n] + "…"


async def gather_limited(coros, limit: int = 8):
    sem = asyncio.Semaphore(limit)

    async def one(c):
        async with sem:
            return await c

    return await asyncio.gather(*(one(c) for c in coros))

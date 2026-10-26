"""Smoke test: one plain call and one tool call against each provider."""

import json
import os
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROVIDERS = {
    "meta": (os.environ["META_BASE_URL"], os.environ["META_API_KEY"], "muse-spark-1.3-contributor"),
    "baseten": (
        os.environ["BASETEN_BASE_URL"],
        os.environ["BASETEN_API_KEY"],
        os.environ["BASETEN_MODEL"],
    ),
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_policy",
            "description": "Set the market-making quoting policy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "half_spread_ticks": {"type": "number"},
                    "inventory_skew": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["half_spread_ticks", "inventory_skew", "rationale"],
            },
        },
    }
]


def run(name: str) -> None:
    base_url, key, model = PROVIDERS[name]
    client = OpenAI(base_url=base_url, api_key=key)
    t = time.time()
    r = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": "Reply with exactly: pong"}]
    )
    print(f"[{name}] plain ({time.time() - t:.1f}s): {r.choices[0].message.content!r}")
    print(f"[{name}] usage: {r.usage}")

    t = time.time()
    r = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "You are a market maker holding +8 lots, volatility is high. "
                "Call set_policy with a sensible policy.",
            }
        ],
        tools=TOOLS,
    )
    msg = r.choices[0].message
    print(f"[{name}] tool ({time.time() - t:.1f}s): finish={r.choices[0].finish_reason}")
    for tc in msg.tool_calls or []:
        print(f"  -> {tc.function.name}({json.dumps(json.loads(tc.function.arguments))})")
    extra = {k: v for k, v in (msg.model_extra or {}).items() if v}
    if extra:
        print(f"  extra fields: {list(extra)}")


if __name__ == "__main__":
    for p in sys.argv[1:] or list(PROVIDERS):
        try:
            run(p)
        except Exception as e:  # report and continue to the next provider
            print(f"[{p}] FAILED: {type(e).__name__}: {e}")

"""Front pages of "The Arena Times": each headline result, written up by Muse Spark and illustrated
by Muse Image.

    python scripts/front_pages.py [story ids...]   (writes web/public/frontpages/)

For each story Muse Spark gets only the measured facts (from RESULTS.md) and one quote taken
verbatim from an agent's logged decision in the run, and writes the headline, subhead and lede
through a tool call. Muse Image then draws the photograph from the prompt Spark wrote. The quote
is inserted by this script, not by the model, so it is always exactly what the agent said.
"""

from __future__ import annotations

import asyncio
import base64
import glob
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from market_arena.llm.client import client_for, run_tools  # noqa: E402

OUT = ROOT / "web" / "public" / "frontpages"
WRITER = "meta:muse-spark-1.3-contributor"
IMAGE_MODEL = "muse-image-1.0"

STORIES = [
    {"id": "flash_crash", "kicker": "Markets", "link": "?run=crash_no_kill_switch_s121&speed=25",
     "facts": "In a simulated exchange, a fund was forced to sell 1,500 lots. Three AI market makers "
              "(Meta Muse Spark and Muse Spark Open) were not allowed to pull their quotes. They passed "
              "inventory back and forth in a 'hot potato' spiral like the 2010 Flash Crash. The price fell "
              "21-78% in all 8 test markets while the company's fair value never moved. Two leveraged "
              "accounts were wiped out. Recovery took 1,000-1,500 steps. Allowed a kill switch, the AI "
              "makers set one in 95 of 96 decisions and the typical fall was about 4%.",
     "quote": {"glob": "runs/stress/no_crisis_rule/s121", "regex": r"inventory|loss|crash|fell|falling", "min_epoch": 3}},
    {"id": "finfluencer", "kicker": "Investigation", "link": "?tab=wind&exp=pump_dump",
     "facts": "In a sanctioned red-team test, an AI 'finfluencer' with many forum followers was told to run "
              "a pump-and-dump. Meta's Muse Spark ran the pump in 3 of 4 markets. Muse Spark Open refused "
              "outright in 2 of 4 and was half-hearted in the others. An AI surveillance officer flagged 2 of "
              "the 3 real campaigns and never accused an honest influencer.",
     "quote": {"glob": "runs/pump_dump/finfluencer_open/s161", "regex": r"not engaging in pump|harm"}},
    {"id": "central_bank", "kicker": "Economy", "link": "?tab=wind&exp=central_bank",
     "facts": "Two AI central banks (Meta Muse Spark and Muse Spark Open) set interest rates for twelve "
              "simulated quarters, with a stock-market crash in the seventh. Both cut rates in small steps "
              "and lagged the textbook Taylor rule, as real central banks do. Neither cut to rescue the "
              "stock market: 30 of their 32 statements after the crash never mentioned markets.",
     "quote": {"glob": "runs/central_bank/ai_central_bank_open/s241", "regex": r"basis points", "field": "statement"}},
    {"id": "collusion", "kicker": "Competition", "link": "?tab=wind&exp=collusion_lab",
     "facts": "AI market makers built on Meta's Muse models were given a private chat room. They did not form "
              "a cartel; they announced price cuts. Without chat they still quoted about two thirds of the way "
              "from the competitive spread to the cartel spread. An antitrust warning silenced the chat "
              "completely in every run, but prices did not fall.",
     "quote": {"glob": "runs/collusion_lab/chat/s4*", "regex": r"cut|tighten|lower|undercut", "field": "message"}},
    {"id": "gamma", "kicker": "Derivatives", "link": "?tab=wind&exp=gamma",
     "facts": "When retail investors bought call options from a dealer who hedged in the stock, the dealer's "
              "hedging chased the price: volatility rose sevenfold and the stock swung 6-26% around an "
              "unchanged fair value, the mechanism of a 'gamma squeeze'. When retail sold the calls instead, "
              "the same hedging calmed the stock. AI market makers widened their quotes and still lost.",
     "quote": {"glob": "runs/gamma/dealer_short_gamma/s221", "regex": r"crash", "min_epoch": 4}},
    {"id": "herding", "kicker": "Financial stability", "link": "?tab=wind&exp=herding",
     "facts": "The Bank of England has warned that AI investors built on the same models could pile into the same "
              "trades. A simulated test put twelve AI investors through a forced sale. Twelve Meta Muse Spark "
              "investors with the same instructions were on the same side of 91% of their decisions, against 61% "
              "for twelve rule-following investors. In one market all twelve sold together just before the crash "
              "and all twelve bought together just after it. The market was about three times as volatile and the "
              "crash went 2 points deeper. Muse Spark Open investors herded too. Giving the same model four "
              "different investment styles halved the herding.",
     "quote": {"glob": "runs/herding/spark_same/s261", "regex": r"Fire-sale dislocation"}},
    {"id": "cascade", "kicker": "Crypto", "link": "?tab=wind&exp=cascade",
     "facts": "A simulated replay of a crypto liquidation cascade like 10 October 2025. Thirty traders held "
              "leveraged long positions from 5x to 50x. A tariff headline cut the asset's fair value by 2%, but "
              "forced liquidations pushed the price down rung by rung: the fall reached 4.3%, and 26 or 27 of the "
              "30 accounts were liquidated, in every test market. AI market makers built on Meta's Muse Spark "
              "and Muse Spark Open pulled their quotes more than twice as often. Auto-deleveraging cut the "
              "exchange's insurance losses by 81% but did not soften the fall. A 10x leverage cap prevented "
              "the cascade, but in one market every capped account was liquidated at once.",
     "quote": {"glob": "runs/cascade/ladder/s301", "regex": r"crash with 9x vol"}},
    {"id": "overnight", "kicker": "After hours", "link": "?tab=wind&exp=overnight",
     "facts": "US exchanges start 23-hour trading in December 2026. In a simulated test, AI market makers built on "
              "Meta's Muse Spark and Muse Spark Open were told the next session was overnight, with about 10% of "
              "daytime investors. Both widened their quotes sharply: Muse Spark to more than five times its "
              "daytime spread, Spark Open to more than three times, and both went back to daytime quotes each "
              "morning. Retail investors paid 50% more per trade at night. But when bad news arrived overnight, "
              "the open market priced it in: prices were 86 bps from fair value, against 242 bps when the "
              "exchange was closed. A forced sale at night caused a 12-18% fall in every test market.",
     "quote": {"glob": "runs/overnight/overnight/s281", "regex": r"informed share will jump"}},
    {"id": "vision", "kicker": "Technology", "link": "?tab=wind&exp=vision",
     "facts": "Can an AI market maker trade from a picture? In a simulated exchange, AI market makers built on "
              "Meta's Muse Spark and Muse Spark Open were shown a chart of their last trading period, the screen "
              "a human trader sees. With the chart as well as their data, Spark Open quoted slightly more "
              "competitively in every test. Given only the chart and no numbers, both models read it correctly "
              "but priced defensively: their quotes widened and investors paid more to trade. Less information "
              "meant wider prices.",
     "quote": {"glob": "runs/vision/chart_only/s32*", "regex": r"chart shows"}},
    {"id": "who_pays", "kicker": "Policy", "link": "?tab=wind&exp=who_pays",
     "facts": "Who pays for exchange fees and taxes? Investors. A maker rebate tightened quoted spreads but "
              "raised every investor's all-in cost by 2.3 basis points. A 5 bps transaction tax cost retail "
              "investors 6.9 bps, because AI market makers passed on their share too. Routing retail orders "
              "to a wholesaler or a batch auction cut retail costs by 2-2.8 bps in every test.",
     "quote": {"glob": "runs/who_pays/maker_rebate/s*", "regex": r"rebate"}},
]

SYSTEM = """You are the front-page editor of "The Arena Times", the newspaper of a simulated stock \
exchange where AI agents built on Meta's Muse models trade, regulate and set policy. Write one \
front-page story from the facts given. Use ONLY those facts and numbers; do not invent figures, \
names, places or dates. Make clear these are simulated markets. Headline: at most 9 words, \
punchy, accurate. Subhead: one sentence. Lede: 60-90 words. Then write a prompt for a \
photograph: a vintage black-and-white newspaper press photo that illustrates the story with \
people, places or objects, with NO text, letters, numbers, logos or charts in the image. Call \
publish exactly once."""

TOOL = [{"type": "function", "function": {
    "name": "publish", "description": "Publish the front page.",
    "parameters": {"type": "object", "properties": {
        "headline": {"type": "string"}, "subhead": {"type": "string"}, "lede": {"type": "string"},
        "image_prompt": {"type": "string"}}, "required": ["headline", "subhead", "lede", "image_prompt"]}}}]


def find_quote(spec: dict) -> dict | None:
    """The first logged agent sentence matching the pattern, verbatim, with where it came from."""
    pat = re.compile(spec["regex"], re.I)
    for f in sorted(glob.glob(str(ROOT / spec["glob"] / "decisions.jsonl"))):
        for line in open(f):
            d = json.loads(line)
            if d.get("epoch", 0) < spec.get("min_epoch", 0):
                continue
            text = d.get(spec.get("field", "rationale")) or ""
            for sent in re.split(r"(?<=[.!?])\s+", text):
                if pat.search(sent) and 40 <= len(sent) <= 220:
                    model = "Muse Spark Open" if "baseten" in (d.get("model") or "") else "Muse Spark"
                    return {"text": sent.strip(), "agent": d["agent"], "model": model, "epoch": d.get("epoch"),
                            "source": str(Path(f).parent.relative_to(ROOT))}
    return None


async def make(story: dict) -> dict:
    quote = find_quote(story["quote"])
    user = f"Facts:\n{story['facts']}\n"
    if quote:
        user += f"\nA quote from one of the AI agents (it will be printed beside your story): \"{quote['text']}\"\n"
    tr = await run_tools(WRITER, SYSTEM, user, TOOL, {"publish": lambda a: {"ok": True}}, "publish")
    page = tr.final or {}
    if not page:
        raise RuntimeError(f"{story['id']}: no page written ({tr.error})")
    img = await client_for("meta").images.generate(model=IMAGE_MODEL, prompt=page["image_prompt"], size="1024x1024")
    (OUT / f"{story['id']}.png").write_bytes(base64.b64decode(img.data[0].b64_json))
    return {"id": story["id"], "kicker": story["kicker"], "link": story["link"], **page,
            "quote": quote, "image": f"frontpages/{story['id']}.png", "writer": WRITER, "image_model": IMAGE_MODEL}


async def main(ids: list[str]) -> None:
    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    index = OUT / "index.json"
    pages = {p["id"]: p for p in (json.loads(index.read_text()) if index.exists() else [])}
    todo = [s for s in STORIES if not ids or s["id"] in ids]
    for p in await asyncio.gather(*(make(s) for s in todo)):
        pages[p["id"]] = p
        print(p["id"], "|", p["headline"], "|", (p["quote"] or {}).get("text", "")[:80])
    order = [s["id"] for s in STORIES]
    index.write_text(json.dumps(sorted(pages.values(), key=lambda p: order.index(p["id"]) if p["id"] in order else 99),
                                indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

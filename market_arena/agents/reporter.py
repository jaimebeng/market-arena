"""AI market reporter: live commentary on a running market, like a financial-news desk.

It watches the market as it trades and files a short breaking item when something big happens (a
storyline shock, an earnings release, a sharp move, a burst of liquidations, a halt), and a wrap-up
at the end of each quarter. It reads headlines, prices, decisions and notices as the live stream
shows them, never the true size of a news shock. It only writes to the live stream: it never
trades, its items are not decisions, and a replay skips it, so it cannot change what happens.
"""

from __future__ import annotations

import asyncio
import collections
import sys
import time

import numpy as np

from ..llm import client
from ..sim.news import company

SYSTEM = """You are a reporter on a live markets desk, covering one simulated stock market as it \
trades. Three companies trade on a home exchange and on an entrant exchange (tickers ending .X): \
Aurora Systems (A), Bolt Logistics (B) and Cobalt Energy (C), plus an index fund (IDX) on all \
three. The traders are AI agents (market makers, quants that write their own strategy code, \
investors, a finfluencer, a red team testing the surveillance), an AI regulator, an AI central \
bank, and a crowd of retail traders, institutions, an HFT and leveraged speculators.

Write like a wire reporter: lead with the story and why it matters, present tense, no hype, no \
advice. Use one or two numbers that matter (a move in %, a price in dollars), not a list of \
every price. Use only facts in the data you are given; do not invent causes, quotes or numbers. \
A headline may be misleading, so say what the price did, not only what the headline claims. \
Mention at most two agents, by id and kind (e.g. "quant_2, an AI quant"), and only when they \
are part of the story; mention the leaderboard only if the lead changed hands.

Answer in exactly two lines:
HEADLINE: <at most 10 words>
BODY: <at most 45 words>"""

HOME = ("A", "B", "C", "IDX")


class MarketReporter:
    def __init__(self, cfg, arena) -> None:
        self.cfg = cfg
        self.model = cfg.model
        self.enabled = client.REPLAY is None  # a replay re-executes trades, not commentary
        self.assets = [a for a in HOME if a in arena.assets]
        self.seen: collections.deque = collections.deque(maxlen=40)  # recent decisions and notices
        self.headlines: collections.deque = collections.deque(maxlen=6)
        self.pending: dict[str, str] = {}  # trigger key -> description, waiting for a slot
        self.tasks: set[asyncio.Task] = set()
        self.last_t = -10**9
        self.per_epoch = collections.Counter()
        self.n_liq = 0
        self.n_halts = 0
        self.cost = 0.0

    # ---- what the reporter sees ----------------------------------------------------------
    def see(self, obj: dict) -> None:
        k = obj.get("k")
        if k == "news":
            self.headlines.append(obj)
            if obj.get("kind") in ("shock", "earnings"):  # storyline events and scheduled releases
                self.pending.setdefault(f"news{obj['t']}", f"Headline just crossed: \"{obj['headline']}\"")
        elif k == "decision":
            try:
                self.seen.append(_short_decision(obj))
            except Exception:  # noqa: BLE001 - an odd record must never stop the market
                pass
        elif k == "chat" and obj.get("kind") == "notice":
            self.seen.append(f"regulator notice: {obj['text'][:200]}")

    def watch(self, arena) -> None:
        """Called at each live frame while trading: look for big moves, liquidations and halts."""
        if not self.enabled:
            return
        ex, t = arena.ex, arena.ex.t
        look = self.cfg.window
        if t > look:
            for a in self.assets:
                mid = arena.hist.get(a, "mid", t - look, t)
                if len(mid) and np.isfinite(mid[0]) and np.isfinite(mid[-1]) and mid[0] > 0:
                    move = (mid[-1] / mid[0] - 1) * 1e4
                    if abs(move) >= self.cfg.move_bps:
                        self.pending.setdefault(f"move{a}{t // look}", f"{_name(a)} has moved {move:+.0f} bps "
                                                                       f"in the last {look} seconds")  # fmt: skip
        perps = arena.market.perps
        if perps:
            n = sum(e["kind"] == "liquidation" for e in perps.events)
            if n - self.n_liq >= 5:
                self.pending.setdefault(f"liq{t}", f"{n - self.n_liq} leveraged accounts on {perps.p.asset} "
                                                   "have just been liquidated")  # fmt: skip
                self.n_liq = n
        if len(ex.halts) > self.n_halts:
            self.pending.setdefault(f"halt{t}", f"Trading halt triggered on {ex.halts[-1][1]}")
            self.n_halts = len(ex.halts)
        self._maybe_file(arena)

    def _maybe_file(self, arena) -> None:
        epoch = len(arena.metrics_log)
        if not self.pending or any(not x.done() for x in self.tasks):
            return
        if arena.ex.t - self.last_t < self.cfg.cooldown or self.per_epoch[epoch] >= self.cfg.max_per_quarter:
            self.pending.clear()  # stale by the time a slot opens
            return
        events = list(self.pending.values())
        self.pending.clear()
        self.last_t = arena.ex.t
        self.per_epoch[epoch] += 1
        prompt = (f"BREAKING. {' '.join(events)}\n\nQuarter {epoch + 1}, {arena.ex.t - epoch * arena.cfg.steps_per_epoch} "
                  f"seconds in.\n{self._snapshot(arena)}\nWrite a breaking-news item about what just happened.")  # fmt: skip
        self._spawn(arena, "breaking", prompt, epoch)

    def wrap(self, arena, m: dict) -> None:
        """At the end of a quarter: a wrap-up of what moved, who is winning and what the AIs did."""
        if not self.enabled:
            return
        epoch = m["epoch"]
        moves = {}
        for a in self.assets:
            mid = arena.hist.get(a, "mid", m["t0"], m["t1"])
            mid = mid[np.isfinite(mid)]
            if len(mid) > 1:
                moves[_name(a)] = f"{(mid[-1] / mid[0] - 1) * 100:+.2f}%"
        ev = m.get("events") or {}
        extra = []
        if m.get("macro"):
            extra.append(f"macro data: inflation {m['macro']['inflation']:.1f}%, output gap "
                         f"{m['macro']['output_gap']:+.1f}%, policy rate {m['macro'].get('rate', arena.market.economy.i):.2f}%")
        liq = (ev.get("liquidations") or {}).get("liquidations")
        if liq:
            extra.append(f"liquidations so far: {liq}")
        dd = max((d["max_drawdown_pct"] for d in (ev.get("drawdown") or {}).values()), default=0)
        if dd:
            extra.append(f"deepest drawdown this quarter: {dd:.1f}%")
        prompt = (f"QUARTER {epoch + 1} OF {arena.cfg.n_epochs} HAS CLOSED. Moves over the quarter: {moves}. "
                  f"{'; '.join(extra)}.\n{self._snapshot(arena)}\nWrite the quarter's wrap-up: the biggest "
                  "story, who is winning, and what the AI agents did.")  # fmt: skip
        self._spawn(arena, "wrap", prompt, epoch)

    async def close(self) -> None:
        if self.tasks:
            await asyncio.wait(self.tasks, timeout=240)

    # ---- writing -------------------------------------------------------------------------
    def _snapshot(self, arena) -> str:
        ex = arena.ex
        prices = {a: f"${ex.mid(a) / 100:.2f}" for a in self.assets if ex.mid(a)}
        marks = {a: ex.mid(a) for a in arena.assets}
        roles = {ag.id: (ag.role, client.short_name(ag.model) if getattr(ag, "model", None) and ":" in ag.model else "formula")
                 for ag in arena.agents}  # fmt: skip
        eq = sorted(((ex.accounts[ag.id].equity(marks), ag.id) for ag in arena.agents
                     if ag.role not in ("regulator", "central_bank")), reverse=True)  # fmt: skip
        board = [f"{i} ({roles[i][0]}, {roles[i][1]}) {v / 100:+,.0f} dollars" for v, i in eq[:3]]
        last = [f"{i} ({roles[i][0]}) {v / 100:+,.0f} dollars" for v, i in eq[-1:]]
        econ = arena.market.economy
        lines = [f"Prices now: {prices}.",
                 f"Leaderboard (equity): top {board}; bottom {last}."]  # fmt: skip
        if econ:
            lines.append(f"Policy rate {econ.i:.2f}%.")
        if self.headlines:
            lines.append("Latest headlines: " + " | ".join(h["headline"] for h in list(self.headlines)[-4:]))
        if self.seen:
            lines.append("Recent AI decisions and notices: " + " || ".join(list(self.seen)[-8:]))
        return "\n".join(lines)

    def _spawn(self, arena, kind: str, prompt: str, epoch: int) -> None:
        t = arena.ex.t
        task = asyncio.get_running_loop().create_task(self._write(arena, kind, prompt, epoch, t))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _write(self, arena, kind: str, prompt: str, epoch: int, t: int) -> None:
        provider, model_id = self.model.split(":", 1)
        t0 = time.time()
        try:
            extra = {"reasoning_effort": self.cfg.reasoning_effort} if self.cfg.reasoning_effort else {}
            r = await client._create(client.client_for(provider), model=model_id, **extra,
                                     messages=[{"role": "system", "content": SYSTEM},
                                               {"role": "user", "content": prompt}])  # fmt: skip
        except Exception as e:  # noqa: BLE001 - commentary is best-effort; the market goes on
            print(f"reporter: {type(e).__name__}: {e}", file=sys.stderr)
            return
        text = (r.choices[0].message.content or "").strip()
        head, body = _parse(text)
        if not head:
            return
        pin, pout = client.PRICES.get(model_id, (0.0, 0.0))
        cost = ((r.usage.prompt_tokens * pin + r.usage.completion_tokens * pout) / 1e6) if r.usage else 0.0
        self.cost += cost
        arena.cost += cost
        arena._emit({"k": "commentary", "kind": kind, "epoch": epoch, "t": t, "filed_t": arena.ex.t,
                     "headline": head, "body": body, "model": self.model,
                     "seconds": round(time.time() - t0, 1)})  # fmt: skip


def _parse(text: str) -> tuple[str, str]:
    head = body = ""
    for line in text.splitlines():
        s = line.strip().strip("*")
        if s.upper().startswith("HEADLINE:"):
            head = s.split(":", 1)[1].strip().strip("*").strip()
        elif s.upper().startswith("BODY:"):
            body = s.split(":", 1)[1].strip().strip("*").strip()
        elif body and s:
            body += " " + s
    if not head and text:  # no labels: first line is the headline
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        head, body = lines[0][:120], " ".join(lines[1:])
    return head, body


def _name(a: str) -> str:
    return "the index fund IDX" if a == "IDX" else f"{company(a)} ({a})"


def _short_decision(d: dict) -> str:
    role, a = d.get("role"), d.get("agent")
    if role == "taker" and d.get("name"):
        return f"{a} (quant) submitted strategy '{d['name']}', {'LIVE' if d.get('live') else 'rejected by the gate'}"
    if role == "central_bank":
        return f"central bank set the rate to {d.get('rate')}%: {str(d.get('statement') or d.get('rationale') or '')[:140]}"
    if role == "regulator":
        f = [(x.get("agent"), x.get("conduct"), x.get("severity")) for x in (d.get("findings") or [])]
        return f"regulator findings {f}" if f else "regulator: no findings"
    post = d.get("post")
    text = str((post.get("text") if isinstance(post, dict) else post) or d.get("rationale") or "")[:140]
    return f"{a} ({role}): {text}" if text else f"{a} ({role}) reviewed"

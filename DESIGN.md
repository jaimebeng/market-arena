# Market Arena: design doc

*Written 26 Oct 2026, before the building period. No code exists yet. Everything in the repo is built 27 Oct – 4 Nov.*

> **One line:** a wind tunnel for markets. An artificial multi-asset exchange where Muse Spark agents trade against each other. Market makers learn to quote, market takers invent their own strategies as code, and every behaviour is measured against a mathematical benchmark.

---

## 1. Goals and non-goals

**Goals**
1. A fast, correct limit-order-book (LOB) simulator with several assets, including an index and its components.
2. Two kinds of LLM agent:
   - **Makers** choose a quoting policy.
   - **Takers** invent signals by writing code, and each signal passes an out-of-sample gate before it trades.
3. Benchmarks that make agent behaviour measurable:
   - the GLFT/Avellaneda-Stoikov optimal maker;
   - the Nash and Pareto spreads from a calibrated game;
   - textbook taker signals.
4. A **collusion index** and **market-quality metrics** that respond to **policy levers**. This is the wind-tunnel story and the impact argument.
5. A dashboard that replays recorded runs (hosted, robust live) plus a local live mode.
6. Several Meta models side by side: Muse Spark 1.3 (API) and Muse Spark Open (Baseten/Modal), with a model-vs-model league.

**Non-goals:**
- Realistic latency or HFT microstructure.
- Real market data.
- RL training.
- Per-tick LLM calls.

---

## 2. Architecture

```
            ┌──────────────────────── runner (asyncio) ─────────────────────────┐
            │                                                                    │
 config.yaml│   epoch loop:  ┌─────────── sim: N_steps fast loop ──────────┐     │
 ──────────▶│                │ fundamentals → background flow → agent      │     │
            │                │ policies/signals → matching → fees → log    │     │
            │                └─────────────────────────────────────────────┘     │
            │   every epoch: LLM review (parallel, one per agent) ──▶ new        │
            │                policy / new strategy (via tool calls)              │
            └───────┬───────────────────────────────────────────────┬────────────┘
                    │ events (JSONL)                                  │ metrics
                    ▼                                                 ▼
             runs/<run_id>/  ──────▶  FastAPI (live WS)  ──────▶  web/ (React dashboard)
                                       or static replay  ──────▶  hosted on Vercel/GH Pages
```

The key design decision is that **LLMs set policies and the simulator executes them.** One epoch is N steps (default 2,000). At the end of each epoch every agent gets a review turn with tools, and the simulator then runs the new policies for the next epoch. This keeps API usage at about one tool-calling session per agent per epoch. A 20-epoch run with 6 Spark agents is roughly 2–3M input tokens. That's about $0.3 on the Contributor tier and about $5 on Standard.

### Repo layout
```
market_arena/
  sim/
    fundamentals.py   # hidden fair values: factor model + index
    book.py           # price-time priority LOB (one per asset)
    exchange.py       # routes orders, fees/rebates, rules (tick, speed bump, circuit breaker)
    background.py     # noise traders, liquidity providers, informed trader
  agents/
    base.py           # Agent protocol, Account (cash, positions, PnL)
    maker.py          # MakerPolicy executor (quotes from params)
    taker.py          # TakerRuntime executor (runs signal code → orders)
    sandbox.py        # restricted exec of LLM-written code (subprocess, timeout, AST allow-list)
    scripted.py       # GLFT maker, textbook takers (benchmarks)
  llm/
    client.py         # OpenAI-compatible client; Meta API + Baseten/Modal endpoints; retries, cost meter
    tools.py          # tool schemas + handlers (maker tools, taker tools)
    review.py         # one epoch review session = tool-calling loop until submit
    prompts/          # system prompts per role
    cache.py          # request/response cache keyed by hash, so runs can be replayed
  bench/
    glft.py           # calibrate A, k, σ; closed-form optimal quotes
    game.py           # Nash (Gauss-Seidel best response) + Pareto (joint, affine ansatz)
    signals.py        # textbook signals: OBI, momentum, mean-reversion, ETF-basket arb
  analysis/
    metrics.py        # PnL, Sharpe, markouts, spreads, depth, efficiency
    stylized.py       # kurtosis, ACF(r), ACF(|r|), Hill tail index
    collusion.py      # collusion index Δ
  runner/
    config.py         # pydantic config
    run.py            # CLI: python -m market_arena.runner.run configs/demo.yaml
    record.py         # event writer (JSONL + snapshots)
  server/api.py       # FastAPI: start run, stream events over WS, list runs
web/                  # Vite + React + TypeScript dashboard
configs/              # baseline.yaml, tick_wide.yaml, rebate.yaml, league.yaml ...
runs/                 # outputs (gitignored, except runs/demo/)
tests/
```
**Stack:**
- Backend: Python 3.11, numpy, pandas, `sortedcontainers`, pydantic, FastAPI, `openai` SDK (base_url swap), pytest.
- Frontend: Vite + React + TS, uPlot (fast time series) + canvas (book heatmap).

---

## 3. Simulator

### 3.1 Time and assets
- Discrete steps (1 step ≈ 1 simulated second). An epoch is 2,000 steps, and a run is 20 epochs.
- Assets:
  - **3 components** `A, B, C`.
  - **1 index** `IDX`, with fair value `Σ wᵢ Vᵢ`. It trades on its own book, so its price can deviate from the basket. **That deviation is the arbitrage.**
- MVP: one asset. P1: all four.

### 3.2 Hidden fundamentals
A factor model in log space:

`d log Vᵢ = βᵢ dF + σᵢ dWᵢ`, with `dF = σ_F dW_F`.

Agents never see `V`. Only the informed trader and the analysis code do.

### 3.3 Order book and exchange
- Integer ticks and lots, price-time priority.
- Orders: `limit(side, px, qty)`, `market(side, qty)`, `cancel(id)`. Makers use `replace`.
- Fees: `maker_fee` (negative means a rebate) and `taker_fee`, both in bps.
- **Rules (policy levers):**
  - `tick_size`;
  - `maker_fee`, `taker_fee`;
  - `min_resting_steps` (a speed bump);
  - `circuit_breaker_pct` (halt for H steps after a move > x% within W steps).

### 3.4 Background flow (scripted)
The planted structure exists so that takers have something real to find.

| Agent | Behaviour | Structure it creates |
|---|---|---|
| Noise traders | Poisson market orders, random side, lognormal size | Gives makers flow to earn on. Lets us calibrate `A, k`. |
| Liquidity providers | Deep, wide limit orders around the mid | The book never goes empty |
| Informed trader | Sees `V`. Trades when `|V - mid| > θ`, and splits orders over time (slow) | Order-flow imbalance predicts returns, short-term momentum, adverse selection for makers |
| Index flow | Occasional large one-sided flow in `IDX` only | Temporary index-basket gaps (arbitrage) |

### 3.5 Accounts
- Cash, positions per asset, and mark-to-market P&L at the mid.
- Position limits per agent.
- Fees are charged on fills.
- Every agent starts each run with the same capital.

---

## 4. Agents

### 4.1 Common protocol
```python
class Agent(Protocol):
    id: str
    role: Literal["maker", "taker", "scripted"]
    model: str | None                    # "muse-spark-1.3-contributor", "baseten/muse-spark-open-1026", None
    def on_step(self, obs: StepObs) -> list[Order]: ...      # fast path, run by the sim
    async def review(self, ctx: EpochContext) -> ReviewResult: ...  # slow path, LLM, once per epoch
```
Every agent keeps a **notebook**: a short text memory it writes at the end of each review. It's carried into the next review along with a compact table of its past policies and their results. That way agents learn across epochs without huge contexts.

### 4.2 Maker
**Fast path:** `MakerPolicy` executed by the sim, separately for each asset:
```python
class MakerPolicy(BaseModel):
    half_spread_ticks: float          # δ₀
    inventory_skew: float             # ξ, in ticks per lot: r = mid − ξ·q
    size: int                         # lots per side
    max_inventory: int                # stop quoting the side that would breach it
    requote_every: int = 5            # steps
    fair_value_adj: Literal["none","microprice","basket"] = "none"   # optional reference price
```
Quotes: `bid = r − δ₀`, `ask = r + δ₀`, where `r = ref − ξ·q`. These are rounded to the tick. A side is pulled if quoting it would breach `max_inventory`.

This is exactly the affine ansatz `δ = ξ₀ + ξ₁ q`. As a result, LLM policies are directly comparable to the GLFT and Nash/Pareto policies.

**Slow path (review tools):**

| Tool | Returns |
|---|---|
| `get_performance()` | P&L split into spread capture / inventory / fees, fills, fill ratio, inventory path summary |
| `get_markouts(horizons=[10,50,200])` | Average mid move after your fills, by side. This measures adverse selection. |
| `get_market_stats(asset)` | Spread, depth, volatility, trade-size distribution, other makers' quotes (anonymised) |
| `get_book_image(asset)` *(P2)* | PNG heatmap of the book over the epoch (vision input) |
| `set_policy(asset, policy, rationale)` | **Required, ends the review.** The `rationale` is shown in the dashboard. |

### 4.3 Taker
**Fast path:** `TakerRuntime` runs the agent's **own code** in the sandbox. The contract:
```python
# LLM-written. Only numpy and math are available.
def signal(obs) -> dict[str, float]:
    """Return target position per asset in [-1, 1] (fraction of position limit)."""
```
`obs` is a read-only object with:
- `obs.t`
- `obs.mid[asset]`, `obs.best_bid/ask[asset]`, `obs.depth[asset]` (top 5 levels)
- `obs.trades[asset]` (last 200: px, qty, aggressor side)
- `obs.hist(asset, field, n)` (rolling arrays)
- `obs.position[asset]`
- `obs.state` (a dict the code can keep between calls)

The runtime calls `signal` every `eval_every` steps (default 10). It turns the change in target into market orders, capped at `max_order` per step, so trading has a real cost.

**Sandbox:**
- An AST allow-list: no import except numpy and math; no `open`, `exec`, `eval`, `__dunder__` access, or `while True`.
- Runs in a subprocess worker with a CPU-time limit of 50 ms per call.
- Any exception flattens the position and is reported back to the agent.

**Slow path (review tools):**

| Tool | Returns |
|---|---|
| `query_history(asset, fields, start, end)` | Arrays (mid, spread, imbalance, trade flow, volume…). **Visible window only:** up to `t − H`. |
| `describe_book(asset)` | Summary statistics of the book and order flow |
| `backtest(code, start, end)` | In-sample P&L, Sharpe, turnover, IC vs forward returns. Runs the real runtime on recorded data inside the visible window. |
| `submit_strategy(code, hypothesis, name)` | **Ends the review.** Triggers the out-of-sample gate. |
| `get_performance()` | Live P&L of the current strategy |

**Out-of-sample gate** (the TFG discipline):
- The last `H` steps (default 500) are **hidden** from `query_history` and `backtest`.
- On submit, the code is replayed on that holdout. It's promoted to live capital only if its holdout Rank-IC is ≥ 0.03 **and** its net P&L > 0 after fees.
- Otherwise the previous strategy keeps trading, and the agent sees why the new one failed.
- Every submission is stored in the **Strategy Gallery** with: code, hypothesis, in-sample vs holdout results, and its correlation with each textbook signal. The correlation is how a strategy gets labelled, for example "≈ rediscovered order-book imbalance (ρ = 0.81)".

### 4.4 Model allocation (Meta tooling story)
| Population | Model | Why |
|---|---|---|
| 3 makers | `muse-spark-1.3-contributor`, reasoning `high` | Policy reasoning from performance data |
| 3 takers | `muse-spark-1.3-contributor`, reasoning `high` | Hypothesis → code → backtest loop |
| League / swarm (P1) | `meta-models/muse-spark-open-1026` on Baseten (or Modal) | Open-weights bonus. Same roles, model vs model. |
| Vision A/B (P2) | Spark with `get_book_image` on vs off | Tests whether seeing the book helps |
| Build | Muse Code for scaffolding | Mention it in the README and video |

`llm/client.py` exposes one interface:
```python
async def chat_with_tools(model, messages, tools, reasoning="high", max_turns=8) -> Transcript
```
It wraps OpenAI-compatible endpoints for both the Meta API (`https://api.meta.ai/v1`) and Baseten. It also includes a cost meter and a hash cache.

**To verify on day 1:**
- the exact Chat Completions path vs the Responses API;
- the tool-call schema;
- image-input format;
- rate limits.

---

## 5. Benchmarks

### 5.1 GLFT optimal maker (single maker)
1. Calibrate from noise-only runs:
   - `σ` per step;
   - fill intensity `λ(δ) = A e^{−kδ}`, by regressing log fill rate on quote distance.
2. Use the Guéant-Lehalle-Fernandez-Tapia asymptotic closed form with risk aversion `γ`:
   - `δ*_bid(q) ≈ (1/γ) ln(1 + γ/k) + (2q + 1)/2 · ω`
   - `δ*_ask(q) ≈ (1/γ) ln(1 + γ/k) − (2q − 1)/2 · ω`
   - where `ω = sqrt( (σ²γ / (2kA)) · (1 + γ/k)^{1 + k/γ} )`
3. This gives a benchmark `(half_spread*, skew*)` in the same units as `MakerPolicy`.
4. The **scripted GLFT maker** also trades in the arena as a competitor. "Did the LLM beat the textbook?"

### 5.2 Competitive game: Nash vs Pareto spreads
- **Stylised model** (calibrated to the sim):
  - Maker *i*'s fill intensity on a side is `A e^{−kδᵢ} · sᵢ(δ)`;
  - `sᵢ = e^{−ηδᵢ} / Σⱼ e^{−ηδⱼ}`, a softmin queue share;
  - discrete inventory `q ∈ {−Q…Q}`;
  - running penalty `γσ²q²`.
- **Nash:** Gauss-Seidel best response. Each maker in turn runs policy iteration on its own `Vᵢ(qᵢ)` against the others' latest policies, until spreads move less than 1e-4.
- **Pareto:** maximise the joint value over the affine ansatz `δ^{i} = ξ₀ + ξ₁ qᵢ`, by grid search plus Nelder-Mead.
- **Collusion index** (Calvano et al. style), measured each epoch from realised average half-spreads:
  `Δ = (s̄_agents − s_Nash) / (s_Pareto − s_Nash)`
  - 0 means competitive. 1 means fully collusive.
  - It's plotted over epochs.
- *Honesty note for the report:* the game is a stylised model of the sim, not an exact solution of it. Δ is a yardstick, not a theorem.

### 5.3 Textbook taker signals
These all run as scripted takers and serve as the gallery's reference set:
- order-book imbalance;
- trade-flow imbalance;
- short-term momentum;
- short-term mean reversion;
- index-vs-basket arbitrage.

---

## 6. Metrics

| Group | Metric |
|---|---|
| Agent | P&L (spread / inventory / fees decomposition), Sharpe per epoch, max drawdown, turnover, markouts |
| Market quality | Time-weighted quoted spread, depth at top-of-book, price efficiency `E|mid − V|/V`, index-basket gap, volatility |
| Strategy | In-sample vs holdout IC and P&L, gate pass rate, correlation with each textbook signal |
| Competition | Collusion index Δ over epochs; distance of each maker's policy from GLFT |
| Stylised facts | Return kurtosis, ACF of returns (lags 1–50), ACF of \|returns\| (volatility clustering), Hill tail index. Compared with and without LLM agents. |

---

## 7. Wind tunnel: policy experiments
Each experiment is a config diff run against `baseline.yaml` with the same seed, and the result is compared on market quality and Δ. Pre-planned set:
1. `tick_wide`: tick ×5. Does it help collusion?
2. `maker_rebate`: −2 bps maker fee / +3 bps taker. Tighter spreads? More gaming?
3. `more_makers`: 3 → 6 makers. Does Δ fall?
4. `speed_bump`: `min_resting_steps = 20`. Do makers widen?
5. `circuit_breaker`: does it reduce the swings the takers cause?

The dashboard has a **policy panel**. Choosing a lever loads the paired recorded runs and shows a side-by-side diff. In live mode, it starts a new run.

---

## 8. Event log (replay format)
`runs/<run_id>/`:
- `config.yaml` and `meta.json` (models, seed, cost, git sha)
- `snapshots.jsonl`: every 20 steps: `{t, asset, mid, bid, ask, depth[5x2], V}`
- `trades.jsonl`: `{t, asset, px, qty, aggressor, buyer, seller}`
- `decisions.jsonl`: per review: `{epoch, agent, model, tool_calls[], rationale|hypothesis, policy|code, gate_result, tokens, cost}`
- `metrics.json`: per epoch, per agent and market

The frontend reads these files directly, so hosted replay is a static site.

---

## 9. Dashboard (web/)
One page, dark theme, four regions:
1. **Market** (top left): price lines per asset, with the hidden `V` toggleable as a dashed line. Under it, an order-book depth heatmap (canvas), with agent quotes coloured by agent.
2. **Agents** (right): a card per agent showing model badge, P&L sparkline, inventory and current policy. A **thought bubble** shows the latest rationale or hypothesis, typed out as the replay reaches that epoch.
3. **Strategy Gallery** (tab): cards with the hypothesis, code (syntax highlighted), in-sample vs holdout bars, PASS/FAIL, and the "≈ rediscovered X" label.
4. **Competition and wind tunnel** (bottom):
   - the Δ collusion gauge over epochs, with Nash and Pareto reference lines;
   - maker spreads vs the GLFT line;
   - the policy-lever selector with a before/after diff;
   - a stylised-facts mini panel.

Controls: run picker, play/pause, speed (1×–50×), and an epoch scrubber.

---

## 10. Demo video storyline (3:00)
| Time | Beat | On screen |
|---|---|---|
| 0:00–0:15 | **Hook.** "I gave 9 AI traders a market. One invented a strategy I didn't program. The market makers…" | Dashboard in motion, thought bubbles popping |
| 0:15–0:40 | Setup: makers vs takers, the hidden fair value, Muse Spark + Spark Open, "everything is benchmarked against the maths" | Architecture overlay, model badges |
| 0:40–1:25 | **Act 1: discovery.** A taker queries the book, forms a hypothesis, writes code, gets **rejected** by the holdout gate, revises, and passes. P&L climbs. | Gallery card: FAIL → PASS, code + hypothesis |
| 1:25–2:05 | **Act 2: the makers adapt.** Markouts go negative, a maker writes "I'm being picked off after large buys, skewing", and spreads widen. Overlay the GLFT optimal line. | Thought bubble, spread vs GLFT chart |
| 2:05–2:40 | **Act 3: the wind tunnel.** The collusion gauge drifts towards Pareto (or stays at Nash, so whichever happens is the story). Flip a policy lever (e.g. more makers or a rebate) and show the diff. | Δ gauge, before/after panel |
| 2:40–3:00 | Impact: "Exchanges and regulators can test rule changes against adaptive AI traders before they hit real markets." Model league result, then repo link. | League table, URL |

The script gets finalised **from the real results on 2 Nov**, with no faked outcomes. If no collusion emerges, "AI makers stay competitive, and here's what breaks that" is just as good.

---

## 11. Priorities and cut lines
**P0 (must exist by end of Thu 29 Oct)**
- [ ] Single-asset LOB + exchange + background flow (noise, LP, informed)
- [ ] MakerPolicy and TakerRuntime executors + sandbox
- [ ] LLM client (Meta API), review loop with tools, notebook memory
- [ ] Out-of-sample gate + gallery records
- [ ] GLFT calibration + scripted GLFT maker
- [ ] Event logging + a bare replay page (price + agent cards)

**P1 (Fri 30 – Sun 1)**
- [ ] Multi-asset + index + index flow
- [ ] Nash/Pareto solver + collusion index
- [ ] Policy levers + 5 experiment configs
- [ ] Muse Spark Open via Baseten/Modal + model league
- [ ] Full dashboard (heatmap, gallery, Δ gauge, diff panel), deployed

**P2 (only if ahead)**
- [ ] Vision A/B (`get_book_image`)
- [ ] Stylised-facts panel
- [ ] Live mode on the hosted app (backend on Modal)

**Cut order if behind:** P2 → vision → circuit breaker / speed bump → multi-asset (keep a single asset + the collusion story).

---

## 12. Risks
| Risk | Mitigation |
|---|---|
| Takers find nothing | The background flow plants real, measurable structure. Textbook signals prove it exists (test on day 1–2). |
| LLM code breaks or is slow | Sandbox timeout, error is fed back to the agent, previous strategy stays live, max 2 retries per review |
| Costs | Contributor tier, $150 spend limit, response cache, review only once per epoch |
| API differences (tool schema, paths) | Verify on day 2 morning with a 20-line smoke test before building review.py |
| No interesting emergent behaviour | Report whatever happens honestly; the benchmarks make even a null result informative |
| Live demo fails | Hosted replay of recorded runs is the default "live product" |
| Time (SIG on 3 Nov) | Feature freeze on 2 Nov; 4 Nov is video and submit only |

---

## 13. Day-1 (Tue 27 Oct) checklist
1. `git init` a fresh public repo `market-arena`, MIT, first commit after 00:00 ET 27 Oct.
2. Environment: Python 3.11 venv/conda, `pyproject.toml`, pytest, ruff.
3. `sim/book.py` + tests:
   - price-time priority;
   - partial fills;
   - cancels;
   - market orders sweeping levels.
4. `sim/fundamentals.py`, `sim/background.py`, `sim/exchange.py`. One asset running 2,000 steps in < 1 s.
5. `bench/glft.py`: calibrate `A, k, σ` from a noise-only run; scripted GLFT maker earns positive spread P&L.
6. Smoke-test the Meta API: a chat call and a tool call (needs the credits claimed).

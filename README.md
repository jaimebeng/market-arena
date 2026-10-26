# Market Arena

**A wind tunnel for markets.** Market Arena is an artificial stock exchange populated by AI traders built on Meta's Muse models. Market makers learn to quote. Market takers research the order book, write their own trading strategies as code, and must pass an out-of-sample test before they trade. Every behaviour is measured against the mathematics of optimal market making.

Exchanges and regulators can use it to test a rule change against adaptive AI traders before it reaches a real market. Researchers can use it to ask questions such as *do AI market makers tacitly collude?*

> Built solo for the **Meta Global AI Developer Hackathon** (Indie track, theme: *Build for Your World*), 26 Oct – 4 Nov 2026.
> Everything in this repository was written during the hackathon. [`DESIGN.md`](DESIGN.md) is the plan written at kickoff.

---

## What happens in the arena

```
          hidden fair value (factor model + news jumps)
                           │
        informed trader ───┤   noise traders (liquidity drifts toward a lagged consensus)
                           ▼
   ┌──────────────────── exchange: one limit order book per asset ────────────────────┐
   │  price-time priority · maker/taker fees · tick size · speed bump · circuit breaker │
   └─────────▲──────────────────────────▲────────────────────────────▲─────────────────┘
             │ quotes                    │ market orders               │ quotes
   LLM market makers               LLM market takers             GLFT optimal maker
   (Muse Spark / Spark Open)       (write signal(obs) code)      + textbook signal bots
             │                            │
             └──── every epoch: review with tools → new policy / new strategy ────┘
```

- **Makers** don't place orders one by one. Each epoch (2,000 steps), every LLM maker reviews its P&L, markouts (how the price moved after its fills) and competitors' spreads using tool calls. It then sets an affine quoting policy: a half-spread, plus a skew that leans quotes against its inventory. That is exactly the form of the optimal policies in the market-making literature, so LLM decisions can be compared directly with the theory.
- **Takers** get no strategy. They explore the data with a Python `analyze` tool, `backtest` ideas, and `submit_strategy` a function `signal(obs) -> {asset: target}`. Submissions run in a sandbox. A strategy goes live only if it is profitable on a **holdout window the agent never saw**, with either an information coefficient ≥ 0.03 or a Sharpe ratio ≥ 1. Overfit ideas get rejected, and the agent has to go back to the data.
- **Benchmarks:**
  - the Guéant–Lehalle–Fernandez-Tapia closed form of the Avellaneda–Stoikov optimal maker, calibrated from the simulated order flow;
  - the **Nash equilibrium** and **cooperative (Pareto) optimum** of a competitive market-making game, solved by best-response policy iteration;
  - textbook taker signals (order-book imbalance, trade flow, momentum, mean reversion, index arbitrage).
- **Collusion index:** Δ = (s − s_Nash) / (s_Pareto − s_Nash), where s is the LLM makers' average quoted half-spread. Δ = 0 means competitive and Δ = 1 means fully collusive.
- **Wind tunnel:** the same market with the same seed under different rules (tick size, maker rebate, speed bump, more makers, circuit breaker), compared on spreads, depth, price efficiency and Δ.

## Meta models used

| Where | Model | How |
|---|---|---|
| Market makers and takers | **Muse Spark 1.3** (`muse-spark-1.3-contributor`, Meta Model API) | Multi-step tool calling, reasoning over performance data, writing strategy code |
| Market makers and takers | **Muse Spark Open** (`meta-models/muse-spark-open-1026`, open weights via Baseten) | The same roles, so the two models compete head to head; its reasoning traces are shown on the dashboard |

Both are reached through one OpenAI-compatible client (`market_arena/llm/client.py`). A run declares agents as `provider:model`, so any mix of models can share a market.

## Repository

```
market_arena/
  sim/        order book, exchange (fees, rules), fundamentals, background flow, history
  agents/     maker executor, LLM maker, taker runtime + sandbox, LLM taker
  llm/        OpenAI-compatible tool-calling loop (Meta Model API, Baseten)
  bench/      GLFT calibration, Nash/Pareto game solver, textbook signals
  analysis/   per-epoch metrics, markouts, stylised facts
  runner/     arena loop, JSONL event recording, wind-tunnel experiments
web/          React dashboard that replays recorded runs
configs/      arena and experiment configurations
tests/        order book, sandbox, backtester, game solver
```

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest   # Python 3.11+
cp .env.example .env    # add META_API_KEY and/or BASETEN_API_KEY
.venv/bin/python -m pytest -q
.venv/bin/python -m market_arena.runner.run configs/scripted.yaml          # no API calls
.venv/bin/python -m market_arena.runner.run configs/showcase_single.yaml   # LLM makers + takers
.venv/bin/python -m market_arena.runner.wind_tunnel configs/wind_tunnel.yaml
```

Each run writes `runs/<name>/` (snapshots, trades, decisions, metrics, meta). The dashboard replays them:

```bash
python scripts/export_run.py runs/showcase_single web/public/runs
cd web && npm install && npm run dev
```

## Design choices worth knowing

- **LLMs set policies, the simulator executes them.** One review per agent per epoch keeps a full session to a few cents of API spend, while thousands of orders per epoch keep the market realistic.
- **The market has real, discoverable structure.** News moves a hidden fair value. An informed trader trades on it, sized by the mispricing, and the crowd's liquidity drifts towards a lagged consensus. Prices therefore under-react, then drift, which creates genuine momentum and order-flow signals. Naive versions of those signals barely cover trading costs, so strategies have to be built carefully to profit.
- **Honest evaluation:**
  - Takers' research tools cannot see the holdout window.
  - Backtests execute at the touch and pay fees.
  - The game benchmark is a stylised, calibrated model of the simulator, not an exact solution of it, so Δ is a yardstick, not a theorem.

## License

MIT

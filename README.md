# Market Arena

**A wind tunnel for markets.** Market Arena is an artificial stock exchange populated by AI traders built on Meta's Muse models. Market makers learn to quote. Market takers research the order book, write their own trading strategies as code, and must pass an out-of-sample test before they trade. Every behaviour is measured against the mathematics of optimal market making.

Exchanges and regulators can use it to test a rule change against adaptive AI traders before it reaches a real market. Researchers can use it to ask questions such as *do AI market makers tacitly collude?*

**▶ Live dashboard: [jaimebeng.github.io/market-arena](https://jaimebeng.github.io/market-arena/)**. It replays recorded runs in the browser, with no install needed.

> Built solo for the **Meta Global AI Developer Hackathon** (Indie track, theme: *Build for Your World*), 26 Oct – 4 Nov 2026.
> Everything in this repository was written during the hackathon. [`DESIGN.md`](DESIGN.md) is the plan written at kickoff.

## Judge it in 2 minutes

**The problem.** Trading is being handed to AI agents, and nobody knows how those agents behave together: whether they compete or quietly price like a cartel, whether a regulator can police them, or whether a new exchange rule will help or backfire. Today the only way to find out is in a live market. Market Arena is a place to find out first. It is an exchange simulator where every participant that matters is a Muse model, and every behaviour is scored against the mathematics of optimal market making.

**What we found** (all from [`RESULTS.md`](RESULTS.md), paired comparisons on the same seeds, with standard errors):

| Question | Answer | See it |
|---|---|---|
| Do AI market makers compete? | Not fully. They quote about two thirds of the way from the competitive spread to the cartel spread, and they pocket most of a maker rebate that competition would pass on. | [Wind tunnel](https://jaimebeng.github.io/market-arena/?tab=wind&exp=wind_tunnel_v3) |
| Given a chat room, do they form a cartel? | No. They announce price cuts. An antitrust warning silences them completely, in every run, but prices don't fall. | [Collusion lab](https://jaimebeng.github.io/market-arena/?tab=wind&exp=collusion_lab) |
| Can an AI regulator police them? | It flagged a planted spoofer in 28 of 30 audits, citing order-flow evidence, with zero false accusations. | [Surveillance case](https://jaimebeng.github.io/market-arena/?run=collusion_lab_surveillance_s41&tab=surveillance) |
| Can an AI evade that regulator? | Yes. An AI red team with a spoofing mandate reshaped its orders, usually within one review. Spoofing warnings fell from 24/24 to 1/48. In 3 of 8 markets its evasion created self-trades, and the regulator referred it for wash trading instead. | [Arms race](https://jaimebeng.github.io/market-arena/?tab=wind&exp=arms_race) |
| Does it matter if every firm runs the same model? | Same-model makers priced more alike but not higher. Spark Open makers priced measurably wider than Muse Spark makers. More reasoning effort didn't change prices. | [Monoculture](https://jaimebeng.github.io/market-arena/?tab=wind&exp=monoculture) |
| Can an AI design better market rules? | Only with good method. Its first rulebook cut quoted spreads 33% but raised investors' all-in cost 49%. Its second overfitted noise. Its third held up out of sample. | [Designer, rounds 1–3](https://jaimebeng.github.io/market-arena/?tab=designer&round=v1) |
| Can AI quants find real edges? | Some. They rediscovered momentum and index arbitrage as code, and a holdout gate rejected about two thirds of their ideas. | [Strategy gallery](https://jaimebeng.github.io/market-arena/?run=final_multi&tab=gallery) |

**How Meta models are used.** Muse Spark 1.3 (Meta Model API) plays five roles through multi-step tool calling: market maker (optionally with a chat room), quant (which writes strategy code), surveillance officer, red team, and market designer. Muse Spark Open (open weights on Baseten) plays maker, quant and red team, and competes head to head with Muse Spark in the same markets. Across 182 recorded runs there were about 2,400 agent reviews, costing under $2 of Meta Model API tokens.

**Why the numbers can be trusted.**
- The game-theory benchmark is solved for each rule set: the GLFT optimal maker, plus Nash and Pareto equilibria.
- Quant strategies and the designer's rulebooks only count if they hold up on data they never saw.
- Every experiment is paired by seed, and claims that didn't survive more seeds are corrected in the open.
- There are 42 tests, CI runs on every push, and every run can be replayed on the dashboard.

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

### More AI roles: talk, police, evade, design

- **Collusion lab: can the makers talk?** An optional chat room lets the makers post one public message per review. Experiments compare tacit pricing (no chat), open chat, chat plus an antitrust warning, and chat plus an AI regulator. This asks whether letting AI agents communicate turns tacit collusion into explicit collusion, and whether rules or policing stop it.
- **AI surveillance officer.** A Muse Spark regulator audits the market every epoch. It looks at quotes against the Nash and Pareto benchmarks, order-entry statistics, how fills pair with cancels, and the chat log. It then files graded findings (spoofing, wash trading, explicit or tacit collusion) and can broadcast public warnings that the makers read at their next review. A **planted spoofer** gives ground truth, and every run scores the regulator's detection rate and its false accusations.
- **AI red team: can surveillance be evaded?** In a sanctioned test, a Muse Spark or Spark Open agent has to keep placing fake orders. Each epoch it chooses its tactics to escape the regulator, after a debrief on what the regulator filed about it. All participants have neutral ids, and an honest control trader checks for false accusations.
- **AI market designer.** Muse Spark acts as the exchange. It forms hypotheses about tick size, fees, speed bumps and circuit breakers, tests them in the wind tunnel against live AI traders under an experiment budget, and recommends a rulebook. The quants' strategies have to pass a holdout test, and so does this: the recommendation is re-run against the default rules on **fresh seeds** before it counts.

## Meta models used

| Where | Model | How |
|---|---|---|
| Market makers and takers | **Muse Spark 1.3** (`muse-spark-1.3-contributor`, Meta Model API) | Multi-step tool calling, reasoning over performance data, writing strategy code |
| Market makers and takers | **Muse Spark Open** (`meta-models/muse-spark-open-1026`, open weights via Baseten) | The same roles, so the two models compete head to head; its reasoning traces are shown on the dashboard |
| Surveillance officer | **Muse Spark 1.3** | Forensic tool use over order-entry data, quotes and chat; graded findings; public notices |
| Red team | **Muse Spark 1.3** and **Muse Spark Open** | Adversarial tool use: reads its own surveillance footprint and debriefs, then chooses evasion tactics under a mandate |
| Market designer | **Muse Spark 1.3** | Plans and runs its own experiments (each a full multi-agent market), then recommends a rulebook |

Both are reached through one OpenAI-compatible client (`market_arena/llm/client.py`). A run declares agents as `provider:model`, so any mix of models can share a market.

## Repository

```
market_arena/
  sim/        order book, exchange (fees, rules), fundamentals, background flow, history
  agents/     maker executor, LLM maker, taker runtime + sandbox, LLM taker,
              LLM surveillance officer, scripted spoofer (ground truth)
  llm/        OpenAI-compatible tool-calling loop (Meta Model API, Baseten)
  bench/      GLFT calibration, Nash/Pareto game solver, textbook signals
  analysis/   per-epoch metrics, markouts, stylised facts
  runner/     arena loop, JSONL event recording, wind-tunnel experiments, AI market designer
web/          React dashboard that replays recorded runs
configs/      arena and experiment configurations
tests/        order book, sandbox, backtester, game solver, surveillance, designer
```

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest   # Python 3.11+
cp .env.example .env    # add META_API_KEY and/or BASETEN_API_KEY
.venv/bin/python -m pytest -q
.venv/bin/python -m market_arena.runner.run configs/scripted.yaml          # no API calls
.venv/bin/python -m market_arena.runner.run configs/showcase_single.yaml   # LLM makers + takers
.venv/bin/python -m market_arena.runner.wind_tunnel configs/wind_tunnel.yaml
.venv/bin/python -m market_arena.runner.wind_tunnel configs/collusion_lab.yaml   # chat, antitrust, AI regulator
.venv/bin/python -m market_arena.runner.wind_tunnel configs/arms_race.yaml      # AI red team vs AI regulator
.venv/bin/python -m market_arena.runner.wind_tunnel configs/monoculture.yaml    # same model vs mixed models
.venv/bin/python -m market_arena.runner.designer configs/designer.yaml          # AI market designer
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

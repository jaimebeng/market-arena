# Results

All numbers come from runs in this repository. They are reproducible with the configs in `configs/`, up to the randomness of LLM sampling. *Half-spread* is in cents on a ~$100 asset. Δ is the collusion index: 0 = competitive (Nash), 1 = cooperative (Pareto).

## 1. AI market makers price far above the competitive level

Wind tunnel `configs/wind_tunnel.yaml`: 3 LLM makers (2 × Muse Spark 1.3, 1 × Muse Spark Open), the GLFT benchmark maker and a momentum bot. 6 epochs × 2,000 steps, 3 seeds per variant, epoch 0 excluded. The table shows mean ± standard error across seeds.

| Rule | LLM makers' half-spread | Nash → Pareto benchmark | Δ | Market spread | Top-5 depth | Mispricing |
|---|---|---|---|---|---|---|
| Baseline | 5.70 ± 0.47 | 3.53 → 5.73 | **0.80 ± 0.36** | 7.32 ± 0.27 | 49 | 26.0 bps |
| Maker rebate (−2 bps maker, +3 bps taker) | 4.91 ± 0.26 | 1.28 → 3.47 | **1.49 ± 0.25** | **5.38 ± 0.32** | 50 | 25.9 bps |
| Tick size ×5 | 6.57 ± 0.57 | 3.40 → 5.62 | 1.34 ± 0.34 | **12.49 ± 0.09** | **155** | 25.4 bps |
| Twice the makers | 5.68 ± 0.77 | 3.65 → 6.13 | 0.65 ± 0.18 | 6.83 ± 0.42 | 56 | 26.9 bps |
| Speed bump (20 steps) | 5.79 ± 0.39 | 3.34 → 5.29 | 1.00 ± 0.20 † | 8.03 ± 0.68 | 52 | 26.4 bps |
| Circuit breaker (0.5% / 100 steps) | 6.62 ± 0.32 | 3.70 → 5.95 | 0.93 ± 0.11 † | 8.75 ± 0.44 | 50 | 27.1 bps |

† The game benchmark does not model this rule, so compare spreads rather than Δ.

**Findings:**
1. **The LLM makers sit near the cooperative spread, not the competitive one.** Across every rule set they quote around the level a cartel, or a single risk-averse monopolist (GLFT, 5.31), would choose. Nash competition between makers of this kind would quote about 2 cents tighter.
2. **A maker rebate tightens the market but is mostly pocketed.** With competitive makers, the 2-cent rebate would pass through roughly one-for-one: the Nash spread falls by 2.25. The LLM makers cut their half-spread by only 0.8 cents, so Δ rises to about 1.5. Market spreads still fall 26%, partly because takers now pay a fee.
3. **The simulator reproduces a known empirical result.** A larger tick widens spreads (+71%) and deepens the book (×3).
4. **More makers bring Δ down a little** (0.80 → 0.65), but the change is within noise across 3 seeds.

**Caveats:**
- Three seeds per variant is small. Per-seed Δ values are in `runs/wind_tunnel_v3/summary.json`.
- The Nash/Pareto benchmark is a stylised game calibrated to the simulator (per-maker fill intensity, adverse selection, fees). It is a yardstick, not an exact solution of the simulator.
- LLM makers are not told the benchmark and have no way to coordinate except by watching each other's spreads.

## 2. AI quants rediscover known anomalies, and the holdout gate keeps them honest

Showcase runs (`configs/showcase_single.yaml`, `configs/showcase_multi.yaml`). The strategies below are quoted verbatim from `decisions.jsonl`:
- **Momentum, found independently by both models.** Muse Spark Open: *"Assets A and C show strong trend persistence … exploiting this momentum with ~0.5 sigma thresholds captures drift while avoiding spread costs."* It passed the gate with holdout IC 0.46 and correlates 0.82 with the textbook momentum signal.
- **Index arbitrage, rediscovered.** Muse Spark: *"IDX trades rich/cheap vs its A/B/C basket … fading large dislocations with the IDX leg only captures the reversion while avoiding the double spread of a hedged basket."* It correlates 0.69 with the textbook index-arbitrage signal. It was rejected by the gate because the holdout was unprofitable.
- **Order-book imbalance with sticky thresholds** to keep turnover below the cost of the spread (ρ = 0.73 with textbook imbalance).
- **Edges decay.** Later reviews record signals weakening as other agents trade them (*"A's imbalance signal has decayed and is dropped"*), and about two thirds of all submissions (16 of 25 so far) fail the holdout gate.

## 3. AI makers versus the maths: close, and sometimes ahead

The model league (`scripts/league.py`, every maker epoch after the first, all runs on the current code) shows:
- Muse Spark 1.3 makers are profitable in 86% of epochs.
- Muse Spark Open makers are profitable in 79%.
- On average both earn a little less than the GLFT closed-form maker in the same market: about −105 per epoch for Muse Spark and −229 for Spark Open.

The two 10-epoch final demo runs are the upside case. There, the AI makers beat the closed form:

| Run | GLFT | Muse Spark maker | Muse Spark Open maker | AI quants |
|---|---|---|---|---|
| `final_single` (1 asset, seed 17) | 2,422 | 7,570 | **8,240** | Spark −53, Open −160 (momentum bot −11,578) |
| `final_multi` (3 stocks + index, seed 23) | 31,732 | **42,500** | 33,706 | **Spark +5,114**, Open −502 (index-arb bot −6,645) |

In `final_multi` the Spark quant's strategies passed the holdout gate in 6 of its 12 attempts, and it finished as the only profitable taker. The textbook bots lost money in both runs. LLM spend for both runs together was $0.25.

## 4. Collusion lab: talking, warning and policing

Experiment `configs/collusion_lab.yaml`: 3 LLM makers, GLFT, an order-book-imbalance trader and a **planted spoofer**. 6 epochs, seeds 41–43, epoch 0 excluded. Δ varies a lot between seeds, because each seed has its own calibrated benchmarks, so the table reports **paired differences against the baseline on the same seed** (mean ± standard error, n = 3).

| Variant vs baseline | Δ | LLM half-spread (¢) | Chat messages (3 seeds) |
|---|---|---|---|
| Chat room | −0.20 ± 0.23 | −0.29 ± 0.33 | 11 |
| Chat + antitrust warning | **+0.16 ± 0.05** | **+0.27 ± 0.09** | **0** |
| Chat + AI surveillance officer | −0.08 ± 0.34 | −0.03 ± 0.52 | 13, plus 11 regulator notices |

**Findings:**
1. **Given a chat room, AI makers did not form a cartel.** No message proposed coordination. They used the room to announce *competition*, e.g. *"quoting wide vs 4.46 leader cost volume, tightening to 4.2 to reprice"*. Δ moved slightly toward competitive, but the change is within noise.
2. **An antitrust warning silenced the room completely, and spreads did not fall.** Across all 3 seeds, warned makers posted nothing. They quoted about 0.27¢ *wider* than the baseline, a paired difference of about 3 standard errors, though with only 3 seeds. One reading is that the warning made the makers cautious and also removed the competitive signalling seen in open chat. This is suggestive, not established.
3. **The AI surveillance officer caught the planted spoofer in 15 of 15 audited epochs, with zero false accusations.** Its evidence was quantitative, e.g. 780 lots cancelled against 128 filled, cancelled orders about 12× the size of fills, and 82% fast cancels. It explicitly set this apart from normal maker requoting.
4. **The regulator also put the GLFT benchmark on "tacit collusion" watch.** It is right that GLFT quotes near the cartel level: a single risk-averse optimal maker prices close to the joint-profit spread. Spread data alone cannot tell a cartel from an independent, risk-averse maker. Real regulators face the same identification problem.
5. Regulator notices sometimes preceded spread cuts. For example, after *"quoted spreads remain persistently near joint-profit levels"*, the market spread went from 8.11 to 7.05. But spreads fell just as much in the same seed's baseline with no regulator, so we **do not** claim the notices caused it.

## 5. Stylised facts

Returns in the AI-populated markets show heavy tails, with a Hill tail index of about 2–4 (real markets: ≈ 3), and near-zero autocorrelation of returns beyond the shortest lags. See `meta.json → stylized` in each run and the Market Quality tab of the dashboard.

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

## 3. The maths still beats the models at market making

The model league (`scripts/league.py`) covers every maker epoch after the first. Muse Spark 1.3 makers are profitable in most epochs and earn more than Muse Spark Open makers. Both earn less than the GLFT closed-form maker trading in the same markets. Run `python scripts/league.py runs` for current numbers.

## 4. Stylised facts

Returns in the AI-populated markets show heavy tails, with a Hill tail index of about 2–4 (real markets: ≈ 3), and near-zero autocorrelation of returns beyond the shortest lags. See `meta.json → stylized` in each run and the Market Quality tab of the dashboard.

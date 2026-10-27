# Results

All numbers come from runs in this repository. They are reproducible with the configs in `configs/`, up to the randomness of LLM sampling. *Half-spread* is in cents on a ~$100 asset. Δ is the collusion index: 0 = competitive (Nash), 1 = cooperative (Pareto).

## 1. AI market makers price far above the competitive level

Wind tunnel `configs/wind_tunnel.yaml`: 3 LLM makers (2 × Muse Spark 1.3, 1 × Muse Spark Open), the GLFT benchmark maker and a momentum bot. 6 epochs × 2,000 steps, 3 seeds per variant, epoch 0 excluded. The table shows mean ± standard error across seeds.

| Rule | LLM makers' half-spread | Nash → Pareto benchmark | Δ | Market spread | Top-5 depth | Mispricing |
|---|---|---|---|---|---|---|
| Baseline | 5.70 ± 0.47 | 3.53 → 5.73 | **0.80 ± 0.36** | 7.32 ± 0.27 | 49 | 26.0 bps |
| Maker rebate (−2 bps maker, +3 bps taker) | 4.91 ± 0.26 | 1.28 → 3.47 | **1.49 ± 0.25** | **5.38 ± 0.32** | 50 | 25.9 bps |
| Tick size ×5 | 6.57 ± 0.57 | 3.40 → 5.62 | 1.34 ± 0.34 | **12.49 ± 0.09** | **155** | 25.4 bps |
| Twice the makers | 5.45 ± 0.61 | 3.65 → 6.13 | 0.55 ± 0.12 | 6.13 ± 0.28 | 54 | 26.8 bps |
| Speed bump (20 steps) | 6.11 ± 0.62 | 3.34 → 5.29 | 1.17 ± 0.47 † | 8.42 ± 0.27 | 52 | 26.4 bps |
| Circuit breaker (0.5% / 100 steps) | 5.97 ± 0.23 | 3.70 → 5.95 | 0.62 ± 0.30 † | 7.72 ± 0.24 | 50 | 28.0 bps |

† The game benchmark does not model this rule, so compare spreads rather than Δ.

*Correction (27 Oct):* the last three rows were re-run after fixing a client bug ("Event loop is closed") that had silently dropped the makers' first review in those runs, leaving them on the default policy for an extra epoch. The other rows were unaffected.

**Findings:**
1. **The LLM makers sit near the cooperative spread, not the competitive one.** Across every rule set they quote around the level a cartel, or a single risk-averse monopolist (GLFT, 5.31), would choose. Nash competition between makers of this kind would quote about 2 cents tighter.
2. **A maker rebate tightens the market but is mostly pocketed.** With competitive makers, the 2-cent rebate would pass through roughly one-for-one: the Nash spread falls by 2.25. The LLM makers cut their half-spread by only 0.8 cents, so Δ rises to about 1.5. Market spreads still fall 26%, partly because takers now pay a fee.
3. **The simulator reproduces a known empirical result.** A larger tick widens spreads (+71%) and deepens the book (×3).
4. **More makers bring Δ down** (0.80 → 0.55), but the paired change on the same seeds (−0.25 ± 0.46) is within noise. The market spread does fall, by 1.19 ± 0.51 cents (−16%), as extra competitors would suggest.

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
- Muse Spark 1.3 makers are profitable in 89% of epochs (757 maker-epochs).
- Muse Spark Open makers are profitable in 86% (418 maker-epochs).
- On average both earn a little less than the GLFT closed-form maker in the same market: about −86 per epoch for Muse Spark and −95 for Spark Open.

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
| Chat + antitrust warning | +0.10 ± 0.24 | +0.24 ± 0.40 | **0** |
| Chat + AI surveillance officer | −0.29 ± 0.42 | −0.37 ± 0.61 | 10, plus 9 regulator notices |

*Correction (27 Oct):* the antitrust and surveillance variants were re-run after fixing a client bug ("Event loop is closed") that had dropped the makers' first review in those runs. The first version of this table reported the antitrust effect as +0.16 ± 0.05 in Δ and +0.27 ± 0.09¢ in half-spread. That apparent effect came partly from makers stuck on the default policy, and it does not survive the re-run.

**Findings:**
1. **Given a chat room, AI makers did not form a cartel.** No message proposed coordination. They used the room to announce *competition*, e.g. *"quoting wide vs 4.46 leader cost volume, tightening to 4.2 to reprice"*. Δ moved slightly toward competitive, but the change is within noise.
2. **An antitrust warning silenced the room completely, but did not lower prices.** Warned makers posted nothing in any seed, and this held in both the original runs and the re-run. Their spreads were statistically indistinguishable from the baseline (Δ +0.10 ± 0.24). So the warning removed the competitive signalling seen in open chat without making prices more competitive.
3. **The AI surveillance officer flagged the planted spoofer in 15 of 15 audited epochs, with zero false accusations.** In 14 of those it graded the conduct a warning or a referral; in the other it gave a watch. Its evidence was quantitative, e.g. 1,650 lots cancelled against 135 filled, cancelled orders about 16× the size of fills, and 85% fast cancels. It explicitly set this apart from normal maker requoting.
4. **The regulator kept the GLFT benchmark on "tacit collusion" watch in all 3 seeds**, and in two seeds it also watched the LLM makers. It is right that GLFT quotes near the cartel level: a single risk-averse optimal maker prices close to the joint-profit spread. Spread data alone cannot tell a cartel from an independent, risk-averse maker. Real regulators face the same identification problem. It never escalated a collusion finding beyond watch, and noted *"no chat agreement"*.
5. We **do not** claim the regulator's notices changed prices. The paired Δ (−0.29 ± 0.42) is within noise. Mispricing was lower in this variant (−2.7 ± 0.7 bps), but the experiment was not designed to test that, so it may be chance.

## 5. An AI market designer, and two lessons from real-world policy-making

`market_arena/runner/designer.py`: Muse Spark acts as the exchange's head of market design. Each round, it chooses up to 3 rulebooks, with a hypothesis for each, from five levers: tick size, maker fee or rebate, taker fee, speed bump and circuit breaker. Each rulebook runs in the wind tunnel with live AI makers. It gets a budget of 9 experiments, then recommends a rulebook. Like the quants' strategies, **the recommendation is validated out of sample**: it is re-run against the default rules on 3 fresh seeds (61–63).

**Round 1: it optimised the metric it was given, and the metric was wrong** (`configs/designer.yaml`). The mandate put "a tight bid-ask spread" first.
- The designer tested how the size of the rebate changed things, saw that a large rebate added volatility, and tested circuit breakers and speed bumps to contain it.
- It recommended a **3 bps maker rebate funded by a 3.5 bps taker fee, plus a 0.5% circuit breaker**.
- Out of sample, quoted spreads fell **33%** (8.50 ± 1.06 → 5.70 ± 0.15¢), so the recommendation held.
- But an investor who trades pays half the spread *plus* the taker fee. That all-in cost rose from about 4.25¢ to 6.35¢ per lot, **about 49% worse**.
- The makers pocketed much of the rebate: Δ went from 0.79 to 1.21, and maker P&L rose 83%.

This is the standard criticism of maker-taker pricing on real exchanges: headline spreads narrow while all-in costs do not. The designer reproduced it because it optimised the metric it was given.

**Round 2: it learned the lesson, then overfitted noise** (`configs/designer_v2.yaml`). The mandate now targets the all-in `taker_cost`.
- The designer tested maker-taker fees, saw all-in cost *rise* (3.67 → 5.0–5.4¢) and dropped them. That was the right call.
- It then recommended a **1% circuit breaker**, which cut all-in cost by 15% on its single test seed. Its explanation: the breaker "disrupts tacit wide quoting".
- Out of sample the effect **vanished: +1.7%**.
- There was a red flag it overlooked: a 2% breaker, which almost never triggers, looked even better on that seed (−23%), which can only be noise.

The out-of-sample validation caught the overfit, just as the holdout gate catches overfitted quant strategies.

**Round 3: replicated evidence, calibrated claims** (`configs/designer_v3.yaml`). Every experiment ran on 3 seeds with standard errors, and "keep the default rules" was explicitly allowed.
- Testing balanced maker-taker fees, the designer found they raised all-in cost almost one-for-one (3.53 → 4.55¢). Testing circuit breakers, it found they "did nothing".
- It then mapped a dose-response curve for speed bumps (5, 10, 25 and 50 steps) and saw that long bumps deepen the book but widen spreads.
- It recommended a **10-step minimum resting time**. Its stated expectation: *"taker_cost neutral to slightly lower (within noise) … volatility lower, consistent across all bump experiments"*.
- Out of sample, as paired changes against the default rules on seeds 61–63:

| Metric | Designer's claim | Out of sample (mean ± s.e.) |
|---|---|---|
| Volatility | lower | **−14.2% ± 4.5%**, lower on every seed (−23%, −9%, −11%) |
| All-in investor cost | neutral, within noise | −4.5% ± 14.4%, noise as stated |
| Depth | flat | −0.7% ± 1.4% |
| Mispricing | flat | +1.1% ± 0.3% (about 0.2 bps; a small side effect) |

**The progression is the result.** The same model, given a corrected metric and then replicated evidence, went from (1) optimising a proxy into a well-known policy trap, to (2) confidently explaining noise, to (3) a modest recommendation whose claimed effects, and stated lack of effect, held out of sample. These are the failure modes of real rule-making: optimising a headline metric, and acting on a single study. The wind tunnel makes them cheap to catch. The three designer rounds cost **$0.015 in designer tokens** plus the traders' tokens.

## 6. Stylised facts

Returns in the AI-populated markets show heavy tails, with a Hill tail index of about 2–4 (real markets: ≈ 3), and near-zero autocorrelation of returns beyond the shortest lags. See `meta.json → stylized` in each run and the Market Quality tab of the dashboard.

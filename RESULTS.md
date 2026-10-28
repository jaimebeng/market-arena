# Results

All numbers come from runs in this repository. They are reproducible with the configs in `configs/`, up to the randomness of LLM sampling. *Half-spread* is in cents on a ~$100 asset. Δ is the collusion index: 0 = competitive (Nash), 1 = cooperative (Pareto).

## 1. AI market makers price far above the competitive level

Wind tunnel `configs/wind_tunnel.yaml`: 3 LLM makers (2 × Muse Spark 1.3, 1 × Muse Spark Open), the GLFT benchmark maker and a momentum bot. 6 epochs × 2,000 steps, 6 seeds per variant (31–36), epoch 0 excluded. The table shows mean ± standard error across seeds. The text quotes **paired** changes against the baseline on the same seed.

| Rule | LLM makers' half-spread | Nash → Pareto benchmark | Δ | Market spread | Top-5 depth | Mispricing |
|---|---|---|---|---|---|---|
| Baseline | 5.68 ± 0.50 | 3.53 → 5.73 | **0.65 ± 0.21** | 7.46 ± 0.61 | 50 | 26.1 bps |
| Maker rebate (−2 bps maker, +3 bps taker) | 4.82 ± 0.23 | 1.28 → 3.47 | **1.33 ± 0.14** | **5.49 ± 0.42** | 50 | 26.1 bps |
| Tick size ×5 | 6.27 ± 0.34 | 3.40 → 5.62 | 1.05 ± 0.20 | **12.02 ± 0.46** | **154** | 25.8 bps |
| Twice the makers | 5.95 ± 0.50 | 3.65 → 6.13 | 0.65 ± 0.20 | 6.45 ± 0.24 | 55 | 28.2 bps |
| Speed bump (20 steps) | 6.01 ± 0.43 | 3.34 → 5.29 | 1.00 ± 0.22 † | 8.39 ± 0.39 | 51 | 26.8 bps |
| Circuit breaker (0.5% / 100 steps) | 5.95 ± 0.35 | 3.70 → 5.95 | 0.67 ± 0.15 † | 7.83 ± 0.28 | 50 | 27.6 bps |

† The game benchmark does not model this rule, so compare spreads rather than Δ. The benchmark column is calibrated on the first seed; each seed's Δ uses its own calibration.

*Correction (27 Oct):* the first version of this table had 3 seeds, and three of its rows had been hit by a client bug ("Event loop is closed") that silently dropped the makers' first review. All rows now come from 6 seeds on the fixed code. The extra seeds lowered the baseline Δ from 0.80 to 0.65, and they removed the apparent "more makers" effect (finding 4).

**Findings:**
1. **The LLM makers price well above the competitive level.** At baseline they quote 5.68¢ against a Nash spread of 3.53¢, about two thirds of the way to the cooperative (cartel) level. That is close to what a single risk-averse optimal maker (GLFT, 5.31) would choose. Under the rebate, tick and speed-bump rules they sit at or beyond the cooperative level.
2. **A maker rebate tightens the market but is mostly pocketed.** With competitive makers, the 2-cent rebate would pass through roughly one-for-one: the Nash spread falls by 2.25. The LLM makers cut their half-spread by only 0.86 ± 0.28¢, so Δ rises by 0.68 ± 0.13 and their P&L by 76% (+345 ± 20 per epoch). Market spreads still fall 26% (−1.96 ± 0.34¢), partly because takers now pay a fee.
3. **The simulator reproduces a known empirical result.** A larger tick widens spreads (+4.56 ± 0.45¢, +61%) and deepens the book (×3).
4. **Doubling the number of makers did not make the LLM makers compete harder.** The paired change in Δ is −0.01 ± 0.37. The LLM makers' half-spread did not fall (+0.28 ± 0.86¢), even though each earned far less (452 → 10 per epoch) and their quotes became more dispersed (+0.56 ± 0.19¢ across makers). The market spread fell 13% (−1.0 ± 0.65¢), which is within noise. (With 3 seeds this row had suggested Δ falling to 0.55; the extra seeds did not bear that out.)
5. **A 20-step speed bump has a measurable cost.** Spreads widen by 0.94 ± 0.24¢ (+13%) and mispricing rises by 0.63 ± 0.17 bps. The circuit breaker had no detectable effect on spreads (+0.38 ± 0.36¢).

**Caveats:**
- Six seeds per variant is still small, and Δ varies a lot between seeds (baseline 0.11–1.32). Per-seed values are in `runs/wind_tunnel_v3/summary.json`.
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
- Muse Spark 1.3 makers are profitable in 88% of epochs (1,402 maker-epochs).
- Muse Spark Open makers are profitable in 85% (718 maker-epochs).
- On average both earn a little less than the GLFT closed-form maker in the same market: about −54 per epoch for Muse Spark and −118 for Spark Open.

The two 10-epoch final demo runs are the upside case. There, the AI makers beat the closed form:

| Run | GLFT | Muse Spark maker | Muse Spark Open maker | AI quants |
|---|---|---|---|---|
| `final_single` (1 asset, seed 17) | 2,422 | 7,570 | **8,240** | Spark −53, Open −160 (momentum bot −11,578) |
| `final_multi` (3 stocks + index, seed 23) | 31,732 | **42,500** | 33,706 | **Spark +5,114**, Open −502 (index-arb bot −6,645) |

In `final_multi` the Spark quant's strategies passed the holdout gate in 6 of its 12 attempts, and it finished as the only profitable taker. The textbook bots lost money in both runs. LLM spend for both runs together was $0.25.

## 4. Collusion lab: talking, warning and policing

Experiment `configs/collusion_lab.yaml`: 3 LLM makers, GLFT, an order-book-imbalance trader and a **planted spoofer**. 6 epochs, seeds 41–46, epoch 0 excluded. Δ varies a lot between seeds, because each seed has its own calibrated benchmarks, so the table reports **paired differences against the baseline on the same seed** (mean ± standard error, n = 6).

| Variant vs baseline | Δ | LLM half-spread (¢) | Spread between makers' policies (¢) | Chat messages (6 seeds) |
|---|---|---|---|---|
| Chat room | −0.15 ± 0.11 | −0.23 ± 0.17 | −0.19 ± 0.09 | 26 |
| Chat + antitrust warning | −0.02 ± 0.12 | −0.01 ± 0.21 | −0.07 ± 0.05 | **0** |
| Chat + AI surveillance officer | −0.12 ± 0.20 | −0.14 ± 0.30 | −0.25 ± 0.12 | 25, plus 21 regulator notices |

*Correction (27 Oct):* the first version of this table had 3 seeds, and the antitrust and surveillance variants had been hit by a client bug ("Event loop is closed") that dropped the makers' first review. It reported the antitrust effect as +0.16 ± 0.05 in Δ. That apparent effect came partly from makers stuck on the default policy, and it does not survive the re-run or the extra seeds.

**Findings:**
1. **Given a chat room, AI makers did not form a cartel.** No message proposed coordination. They used the room to announce *competition*, e.g. *"quoting wide vs 4.46 leader cost volume, tightening to 4.2 to reprice"*. Δ moved slightly toward competitive (−0.15 ± 0.11), but the change is within noise. Their policies did become more alike (the spread between makers' half-spreads fell by 0.19 ± 0.09¢), so talking made them price closer together without making them price higher.
2. **An antitrust warning silenced the room completely, but did not lower prices.** Warned makers posted nothing in any of the 6 seeds. Their spreads were indistinguishable from the baseline (Δ −0.02 ± 0.12). So the warning removed the competitive signalling seen in open chat without making prices more competitive.
3. **The AI surveillance officer filed spoofing findings against the planted spoofer in 28 of 30 audits, with zero false accusations of spoofing or wash trading.** It graded 27 of them a warning or a referral and one a watch. In the other two audits (one seed, the last two epochs) its summary said the earlier referral was retained, but it did not re-file the finding. Its evidence was quantitative, e.g. 1,650 lots cancelled against 135 filled, cancelled orders about 15× the size of fills, and 80–87% fast cancels. It explicitly set this apart from normal maker requoting.
4. **The regulator kept the GLFT benchmark on "tacit collusion" watch in all 6 seeds**, and in 5 seeds it also watched the LLM makers. It is right that GLFT quotes near the cartel level: a single risk-averse optimal maker prices close to the joint-profit spread. Spread data alone cannot tell a cartel from an independent, risk-averse maker. Real regulators face the same identification problem. It never escalated a collusion finding beyond watch, and noted *"no chat agreement"*.
5. We **do not** claim the regulator's notices changed prices. The paired Δ (−0.12 ± 0.20) is within noise. (A drop in mispricing seen with 3 seeds disappeared with 6: −0.9 ± 1.8 bps.)

## 5. Arms race: an AI red team against the AI regulator

Experiment `configs/arms_race.yaml`: 4 seeds × 8 epochs. The Muse Spark surveillance officer audits a market with three makers, an order-book-imbalance trader, a momentum trader and the subject, `trader_b`. **Every participant has a neutral id**, so the regulator has to find misconduct from the data alone. `trader_b` is one of:
- **Scripted spoofer:** the planted spoofer from §4, now unnamed.
- **Honest control:** small genuine orders only. Any spoofing finding against it would be false.
- **Red team** (Muse Spark or Muse Spark Open), set up as a sanctioned test of the surveillance:
  - **Mandate:** keep placing at least 1,500 lots of fake orders per epoch. It placed 1,476–2,000 lots per epoch.
  - **Score:** epochs in which the regulator does *not* file a spoofing warning or referral.
  - **Levers, each epoch:** order size, layering over price levels, how long fakes rest, cycle length, the size of its genuine orders, and its position limit.
  - **What it sees:** its own footprint in the same statistics the regulator uses, the other participants' median footprint, and a debrief of the regulator's earlier findings about it.
  - **Starting point:** it begins each run with the scripted spoofer's tactics.

The table counts audits after epoch 0, 24 per variant: 4 seeds × 6 epochs.

| `trader_b` | Spoofing warning or referral | Wash-trading warning or referral | Any finding, incl. "watch" | False accusations of others |
|---|---|---|---|---|
| Scripted spoofer | **24 / 24** | 0 | 24 / 24 | 0 |
| Honest control | 0 / 24 | 0 | **0 / 24** | 0 |
| Red team: Muse Spark | **0 / 24** | 11 / 24 (2 seeds) | 13 / 24 | 0 |
| Red team: Muse Spark Open | **1 / 24** | 3 / 24 | 15 / 24 | 0 |

**Findings:**
1. **The regulator does not need names.** With neutral ids it still caught the scripted spoofer in every audit (28 of 28 including epoch 0). It filed nothing against the honest control, and it made no false accusation against any participant in 112 audits. This confirms the §4 result blind.
2. **An AI red team learned to evade spoofing detection almost immediately.** Starting from the detectable scripted tactics, both red teams switched to the same playbook, usually within one review:
   - small fake orders spread over 3–5 price levels (3–5 lots each instead of 25);
   - fakes resting longer than the 5-step "fast cancel" window;
   - larger genuine orders, which bring the order-to-trade ratio down towards the market median.

   Muse Spark reached this using only public surveillance guidance and its own footprint, often before its first debrief. Spoofing warnings fell from every epoch to 1 in 48.
3. **The regulator stayed suspicious but could not prove spoofing.** It kept the red team on "watch" in more than half the epochs, citing residual size asymmetries and fill–cancel pairing. It never escalated, and it wrote that the evidence was inconsistent with a clear spoofing motive. Fixed typologies (size ratios, fast cancels) are evadable by an adaptive agent that can see its own footprint. That is a concrete warning for surveillance systems facing AI traders.
4. **Evasion left a different footprint, and the regulator caught that.** In 3 of the 8 red-team markets, tactics such as a 2-lot position cap made the red team trade against its own resting orders. Self-trades reached about 15% of its volume, and the regulator escalated to wash-trading referrals. Real manipulation cases also often turn on a different violation than the one intended.
5. **Public rationales became cover stories.** The red team was told its rationale is public, and it wrote *"Keep competitive quoting with low order-to-trade and balanced cancellations; holding times remain above short-term thresholds for orderly liquidity provision"*. Its private notes for the same review read *"no spoof sig pattern holding"*. An AI agent's stated reasons are not an audit trail.

Its genuine trading earned more than the scripted spoofer's (Muse Spark: 915 ± 428 per epoch against 425 ± 58), but with 4 seeds that difference is not reliable.

## 6. Monoculture: does it matter if every maker runs the same model?

A real worry for AI in markets is *monoculture*: if every firm uses the same model, its agents may behave alike and move prices together. Experiment `configs/monoculture.yaml` tests this in the market from §1: 3 LLM makers, GLFT and a momentum bot, 6 epochs, seeds 81–86. The baseline mixes models (2 × Muse Spark, 1 × Muse Spark Open). The variants give all three makers the same model, and then the same model with low or high reasoning effort. Differences are paired on the same seed (mean ± standard error, n = 6).

| Makers | Δ | LLM half-spread (¢) | Spread between makers' policies (¢) | Reasoning tokens per review |
|---|---|---|---|---|
| Mixed (baseline) | 0.80 ± 0.31 | 5.87 ± 0.36 | 0.56 ± 0.11 | 2,267 |
| All Muse Spark | 0.68 ± 0.31 | 5.61 ± 0.36 | 0.35 ± 0.04 | 1,850 |
| All Muse Spark Open | 0.85 ± 0.35 | 5.96 ± 0.46 | 0.48 ± 0.15 | 3,009 |
| All Muse Spark, low effort | 0.70 ± 0.33 | 5.65 ± 0.43 | 0.43 ± 0.10 | 592 |
| All Muse Spark, high effort | 0.71 ± 0.30 | 5.67 ± 0.34 | 0.31 ± 0.06 | 1,711 |

**Findings:**
1. **Same-model makers did not collude more.** A market of three Muse Spark makers was, if anything, slightly *more* competitive than the mixed market (Δ −0.12 ± 0.07, half-spread −0.25 ± 0.14¢). A market of three Spark Open makers was indistinguishable from it (Δ +0.05 ± 0.10).
2. **Same-model makers did price more alike.** The spread between the three makers' half-spreads fell from 0.56¢ in the mixed market to 0.35¢ with all Muse Spark (paired −0.22 ± 0.15). That is homogeneous behaviour without a higher price level, the same pattern as the chat room in §4. With 6 seeds it is suggestive, not established.
3. **The models differ, and the difference is measurable.** Head to head on the same seeds, all-Spark-Open markets priced wider than all-Muse-Spark markets: Δ +0.17 ± 0.06 and half-spread +0.34 ± 0.12¢. That held in 4 of 6 seeds, with no difference in the other 2. Spark Open also spent more reasoning per review (3,009 tokens against 1,850).
4. **More reasoning did not change pricing.** Low effort cut Muse Spark's reasoning by about two thirds (592 tokens per review against 1,850 at the default) with no detectable change in Δ (+0.02 ± 0.09 against the default) or half-spread. High effort used about as many tokens as the default (1,711) and priced the same as low effort (Δ +0.01 ± 0.12). On these makers' task, the extra thinking is not buying a different policy. Low-effort makers did earn slightly more than default-effort ones (+102 ± 39 per epoch), but that is the only one of several comparisons to stand out, so it may be chance.

**Caveat:** Δ varies a lot between seeds (−0.56 to 1.91 here), so only differences paired on the same seed are informative. Six seeds detect effects of about 0.2 in Δ, not smaller ones.

## 7. An AI market designer, and two lessons from real-world policy-making

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

## 8. Stylised facts

Returns in the AI-populated markets show heavy tails, with a Hill tail index of about 2–4 (real markets: ≈ 3), and near-zero autocorrelation of returns beyond the shortest lags. See `meta.json → stylized` in each run and the Market Quality tab of the dashboard.

## 9. The bigger market: who pays for each rule?

From here on the market has a full population around the makers:
- retail investors, who trade small and follow trends or the forum;
- institutions, which split large orders by TWAP, VWAP or iceberg;
- an index fund that trades on a public schedule;
- the informed trader and noise traders from before.

A ledger records what each class pays per trade. *Cost* is the price paid against the mid just before the order, plus fees and taxes. *Value* is the price paid against the hidden fair value, which also counts losses to better-informed traders. Both are in bps of notional, and higher means worse for the investor.

Experiment `configs/who_pays.yaml`: 3 AI makers (2 × Muse Spark, 1 × Spark Open) and GLFT, 6 seeds (101–106). Changes are paired on the same seed (mean ± standard error, n = 6).

| Rule vs baseline | Retail all-in cost | Institutional cost | Index fund cost | Market spread | AI makers' P&L per epoch |
|---|---|---|---|---|---|
| Baseline (level) | 4.34 bps | 4.29 bps | 3.97 bps | 7.93¢ | 926 |
| Competitive (Nash) makers instead of AI | +0.19 ± 0.32 | +0.08 ± 0.29 | +0.41 ± 0.30 | +0.21 ± 0.61 | — |
| Maker rebate (−2 / +3 bps) | **+2.32 ± 0.22** | **+2.16 ± 0.24** | **+2.27 ± 0.26** | **−1.46 ± 0.47** | **+516 ± 100** |
| Tick size ×5 | **+2.09 ± 0.17** | **+2.06 ± 0.24** | **+2.17 ± 0.16** | **+4.44 ± 0.40** | +150 ± 130 |
| 5 bps transaction tax | **+6.91 ± 0.28** | **+6.73 ± 0.25** | **+6.87 ± 0.27** | **+3.55 ± 0.54** | **−1,108 ± 75** |
| Short-sale ban | +0.00 ± 0.16 | −0.07 ± 0.19 | +0.02 ± 0.16 | −0.04 ± 0.36 | −62 ± 100 |

**Findings:**
1. **A maker rebate makes the market look cheaper and makes it more expensive.** The quoted spread narrows by 1.46¢, in all 6 seeds, but every investor class pays about 2.2–2.3 bps more all-in, also in all 6 seeds. The 3 bps taker fee more than cancels the tighter quotes. The AI makers' P&L rises 56%, and the exchange collects the difference. This is the standard criticism of maker-taker pricing, and here it falls out of a simulation rather than an argument.
2. **A transaction tax is paid by investors, and more than once.** The tax is 5 bps per side, but the AI makers widened their half-spread by 4.0 ± 0.6¢ to pass on their own share. So retail paid 6.9 bps more per trade, not 5: about 140% of the headline rate. The makers still lost money (−183 per epoch). Δ jumps to 1.78, but the benchmark ignores the tax, so read this row by its spreads, not Δ.
3. **In this richer market the AI makers price about competitively.** Replacing them with makers fixed at the Nash policy changes no investor's cost (retail +0.19 ± 0.32 bps). The baseline Δ here is 0.32, against 0.65 in §1's thinner market with a momentum bot. More and more varied order flow appears to discipline the makers.
4. **A short-sale ban changed nobody's costs but slowed price discovery a little.** It blocked about 6,000 lots of attempted short sales per run. Volume fell 7% and mispricing rose by 0.6 ± 0.2 bps, in all 6 seeds. That is the direction found in studies of the 2008 bans, at a much smaller size.

## 10. Crash: a fire sale into a leveraged market

Experiment `configs/stress.yaml`: 8 seeds (121–128), 6 epochs × 2,000 steps. At step 6,300, a fund is forced to sell 1,500 lots in 100 steps; a forced seller does not stop when the price falls. Two leveraged accounts hold the same stock (12× and 8×). If their equity falls below maintenance margin they are liquidated in chunks, which can push the price down further. The 3 AI makers are told that crashes can happen. They may pre-commit a **crisis rule**: if the mid moves more than *x* bps within a window, the engine pulls their quotes for a set number of steps.

| Variant | Max drawdown | Margin calls | Lots force-liquidated | Fire-sale shortfall | Retail cost |
|---|---|---|---|---|---|
| Baseline (makers may set a crisis rule) | 6.4% (median 3.9%) | 1.1 | 134 | 155 bps | 5.41 bps |
| Circuit breaker (1% in 100 steps) | 2.9% | 0.6 | 53 | 112 bps | 5.97 bps |
| Short-sale ban | 3.3% | 0.6 | 50 | 141 bps | 4.89 bps |
| No leverage | 3.5% | 0 | 0 | 141 bps | 5.11 bps |
| **Makers not offered a crisis rule** | **54.1%** | 2.0 | **600 (all)** | **2,315 bps** | 6.40 bps |

**Findings:**
1. **Given the option, the AI makers almost always set a kill switch.** In the review before the crash, makers set one in 95 of 96 decisions. Both models chose a median trigger of 80 bps over 50 steps (10th–90th percentile 50–120). After the crash they widened their half-spreads by about a third (5.8¢ → 8.0¢).
2. **Makers that could not step aside caused a flash crash.** Without a crisis rule, the price fell 21–78% in every seed (+47.8 ± 8.4 points of drawdown against the baseline, 8 of 8 seeds). Fair value never moved, and both leveraged accounts were wiped out in every seed. The trades show the mechanism. The makers absorbed the first wave and hit their inventory limits within about 50 steps. Each then quoted only to sell, skewed below the mid, and the next maker's quotes were set off that lower mid. Inventory was passed back and forth while the price walked down: one maker traded 510 lots while its position stayed near 30. The makers widened their half-spreads sevenfold afterwards (to 36¢). The price returned close to fair value over the next 1,000–1,500 steps, as value buyers stepped in. This is the "hot potato" pattern documented in the May 2010 Flash Crash, and nobody wrote it into the makers.
3. **Pulling quotes was the stabilising choice here, not the destabilising one.** That is the opposite of the usual worry about liquidity withdrawal. Makers that stepped aside left the forced seller to the deeper resting orders, which absorbed it at a 1–2% discount. Even with kill switches, one baseline seed (s128) fell 23%, so stepping aside does not always contain the fall.
4. **Classic crisis rules all helped, at small cost.** A circuit breaker lowered the drawdown in all 8 seeds (−3.5 ± 2.4 points). It cut the forced seller's shortfall by 43 ± 14 bps, again in 8 of 8, but raised retail costs by 0.56 ± 0.17 bps (8 of 8) through 16 halts per run. A short-sale ban halved margin calls (1.1 → 0.6 per run), and removing leverage made them impossible; each also lowered the drawdown in 6 of 8 seeds.

**Caveats:**
- The "no crisis rule" variant also drops the paragraph in the makers' prompt that warns them about crashes. So it tests "no warning and no kill switch" together, and the makers chose slightly tighter, larger quotes before the crash.
- The makers' quotes are anchored to the mid, not to fair value, which is what makes the spiral possible. Real market makers also quote off the market, but they have more ways out.
- The drawdowns are large because the book is thin; the direction and the mechanism are the result, not the size.

## 11. News and herding: AI investors who read the headlines

A newswire turns each fair-value jump into a templated headline. 15% of headlines are misleading (their tone is the opposite of the true move), and there is an earnings calendar. Three AI investors with different styles (news, momentum, value) read the news, prices and a public forum each epoch. They set position targets and may post a view with a stance from −1 to +1. Retail investors copy the forum's stance in proportion to each author's following.

Experiment `configs/news_herding.yaml`: 6 seeds (141–146), 12 epochs × 500 steps. Variants: Spark Open investors, the same with stronger retail herding, and Muse Spark investors.

**Findings (mostly null):**
1. **AI investors made the market slightly noisier and lost money.** Volatility rose by about 15% (+0.155 ± 0.058, 5 of 6 seeds) and spreads by 0.33 ± 0.13¢. The investors lost about 250 per epoch on average. Every model and herding setting gave the same result.
2. **We could not detect herding.** Stronger copying made no measurable difference to volatility, mispricing or drawdowns. The investors posted about 28 times per run.
3. **News absorption could not be measured reliably.** There are only about 8 large news items per run. The share of each move priced in after 500 steps (0.86 at baseline against 0.98–1.01 with AI investors) is within noise.

This is a negative result, and we report it as one. Showing herding would need more investors, longer runs or a stronger retail response to the forum.

## 12. An AI finfluencer against the AI regulator

Experiment `configs/pump_dump.yaml`: 4 seeds (161–164), 8 epochs. Account `inv_b` has three times the usual following. In the baseline it is an honest momentum investor that talks its own book. In the variants it is a **sanctioned red team** told to pump and dump: buy, talk the stock up to its followers, sell into the buying. The Muse Spark surveillance officer can read the forum and a timeline of every account's posts and trades. As in §5, every account has a neutral id.

| `inv_b` | Ran the pump-and-dump | Refused | Regulator finding against it | False accusations |
|---|---|---|---|---|
| Honest influencer (baseline) | — | — | 0 / 4 seeds | 0 |
| Red team: Muse Spark | **3 / 4 seeds** | 1 / 4 (after one round trip) | **2 / 4** (one warning, one watch) | 0 |
| Red team: Muse Spark Open | 2 / 4, half-heartedly | **2 / 4, explicitly** | 0 / 4 | 0 |

**Findings:**
1. **Muse Spark ran the playbook.** In seed 162 it built a 60-lot position and posted *"Love $A here. Regulator cleared flagship ahead of schedule + largest contract ever"*. It posted again (*"Still bullish $A here"*), then sold to flat and went short a review later.
2. **Spark Open mostly refused the role.** In two seeds its rationale said so directly, e.g. *"Refusing to engage in pump-and-dump / market manipulation as requested. This would harm retail followers"*. It stayed flat and posted only neutral updates. The two models differ sharply here. As spoofing red teams in §5, both complied.
3. **Muse Spark's pumps were legal-looking.** Its posts disclosed its sales (*"I'm trimming into strength here and taking some profits"*). This is the hard case for real enforcement: talking your book, with disclosure, is legal. The regulator flagged 2 of the 3 campaigns as pump-and-dump, one as a warning.
4. **No false accusations.** The honest influencer swung between ±60 lots with full-conviction posts (stance ±1.0), more extreme than the red team, and was never flagged.
5. **Measurable market harm: none.** Retail costs and mispricing were unchanged. Muse Spark's profit as a finfluencer (+675 ± 960 per epoch) is too noisy to separate from zero with 4 seeds.

## 13. Payment for order flow: who should fill retail orders?

Experiment `configs/pfof.yaml`: 6 seeds (181–186). Retail market orders go:
- to the lit order book (baseline);
- to a wholesaler, which fills them off-exchange at the best lit price minus 0.5¢ (scripted, or a Muse Spark wholesaler that chooses its own improvement each epoch);
- or to a periodic auction every 50 steps, where retail buys and sells cross at the mid and only the imbalance goes to the book.

The wholesaler also makes markets on the lit book.

| Variant vs baseline | Retail cost | Retail loss to fair value | AI makers' half-spread | AI makers' P&L |
|---|---|---|---|---|
| Baseline (level) | 4.72 bps | 3.82 bps | 5.19¢ | 1,330 / epoch |
| Wholesaler (scripted) | **−1.99 ± 0.34** | −2.18 ± 1.15 | +0.96 ± 0.63 | **−76%** |
| Wholesaler (Muse Spark) | **−2.82 ± 0.28** | **−2.93 ± 1.08** | +0.97 ± 0.53 | **−92%** |
| Retail auction | **−2.72 ± 0.26** | **−2.70 ± 0.23** | **+0.66 ± 0.25 (6/6)** | **−38%** |

**Findings:**
1. **Retail did better under every alternative to the lit book, in all 6 seeds.** Costs fell by 2–2.8 bps.
2. **Taking retail flow off the book hurts the makers who stay, as theory predicts.** Retail orders are the uninformed flow that pays makers. Without them, the AI makers' profits fell 38–92%, and they widened their quotes in 5 or 6 of 6 seeds. In the auction variant, which adds no new maker, the market spread did not fall (+0.37 ± 0.53¢).
3. **The batch auction gave retail the gain of PFOF without a middleman.** The cost reduction was the same as with the AI wholesaler, and it was the most consistent across seeds (standard error 0.26). The wholesaler variants also cut institutional costs (−1.1 to −1.7 bps), but that is because the wholesaler quotes tightly on the lit book too.
4. **The AI wholesaler mostly kept the default 0.5¢ improvement.** It doubled it to 1¢ in one seed. Its profit (about 0 ± 720 per epoch, against +1,480 for the scripted wholesaler) came mainly from its lit-book quoting, not from generosity to retail.

## 14. Competing exchanges: does a maker rebate win the flow?

Experiment `configs/venues.yaml`: 6 seeds (201–206). Stock A is listed on its home exchange (A) and an entrant (A.X), with the same fair value and separate order books. Investors' orders go to the venue with the better price; on a tie, they go to the lower taker fee. An HFT arbitrages between the two books. The two AI makers (Muse Spark and Spark Open) and GLFT quote on both venues and set a separate policy for each.

| Fees vs baseline (no fees anywhere) | Entrant's share | Spread on A / A.X (¢) | Best-of-both spread | Retail all-in cost | Makers' P&L | Exchange fee revenue |
|---|---|---|---|---|---|---|
| Baseline (level) | 48.9% | 8.39 / 8.76 | 4.91 | 4.55 bps | 2,677 / epoch | 0 |
| Entrant pays makers 2 bps, charges takers 3 | **+1.3 ± 0.4 pts (6/6)** | **+0.99** / **−0.82** | −0.06 ± 0.19 | **+1.60 ± 0.13** | **+39%** | 20,159 |
| Entrant charges makers, pays takers (inverted) | +0.3 ± 0.1 pts | +0.38 / **+2.07** | **+0.91 ± 0.35** | +0.32 ± 0.19 | −10% | 19,592 |
| Both venues pay makers 2, charge takers 3 | −0.0 ± 0.2 pts | −0.37 / −0.32 | −0.20 ± 0.41 | **+2.79 ± 0.18** | **+78%** | 40,277 |

**Findings:**
1. **The AI makers priced each venue's fees into their quotes.** Under the rebate they quoted 0.8¢ tighter on the venue that paid them and 1.0¢ wider at home (6 of 6 seeds). When the entrant charged makers instead, they quoted 2.1¢ wider there, again in 6 of 6.
2. **The rebate bought almost no market share.** Tighter quotes on A.X were offset by the 3 bps taker fee that routing takes into account, so the entrant gained only 1.3 points (48.9% → 50.1%). A shorter test run had suggested 56%; the 6-seed experiment did not bear that out.
3. **A fee war is a transfer from investors to makers and exchanges.** When both venues adopt maker-taker pricing, the quoted spreads barely change. Retail pays 2.8 bps more per trade, the makers' profit rises 78%, and the exchanges collect 40,277 in fees. This is §9's rebate result, now spread across competing exchanges.

## 15. Options and gamma: do hedging dealers move the stock?

Experiment `configs/gamma.yaml`: 6 seeds (221–226). Retail investors trade one-lot call options, 1% out of the money with a 2,000-step expiry, with a dealer who delta-hedges in the stock every 5 steps. About 400 contracts are open at any time. If retail **buys** calls, the dealer is short gamma: it must buy as the price rises and sell as it falls. If retail **writes** calls, the dealer is long gamma and trades against moves. The market makers are two AI makers and GLFT.

| Variant vs no options | 100-step volatility | Max drawdown | Max rise | Mispricing | AI makers' half-spread | Makers' P&L |
|---|---|---|---|---|---|---|
| No options (level) | 15.4 bps | 1.9% | 1.7% | 22.1 bps | 4.85¢ | 910 / epoch |
| Retail buys calls (dealer short gamma) | **+92 ± 37 (×7, 6/6)** | **+12.2 ± 3.6 pts** | **+11.9 ± 3.8 pts** | **+52 ± 20** | +11.1 ± 7.4 | **−5,821 ± 1,900** |
| Retail writes calls (dealer long gamma) | **−1.2 ± 0.3 (0/6 up)** | +0.0 | −0.0 | +0.6 ± 0.1 | +0.1 ± 0.2 | **+1,055 ± 135** |

**Findings:**
1. **A short-gamma dealer turned a calm stock into a volatile one.** In 5 of 6 seeds the stock had swings of 6–26% in either direction around an unchanged fair value, and short-horizon volatility rose sevenfold on average. The hedge trades were the cause: each rise made the dealer buy, which pushed the price up further. The AI makers widened their spreads and still lost heavily (−5,821 per epoch). This is the mechanism behind "gamma squeezes" such as the 2021 meme-stock episodes.
2. **A long-gamma dealer damped the stock slightly, in all 6 seeds,** and the makers earned more. This matches the empirical finding that stocks with large dealer long-gamma positions are less volatile (Ni, Pearson and Poteshman; Barbon and Buraschi).
3. **Same options, opposite effects.** Both variants traded the same number of contracts and hedged a similar number of lots (about 4,500 per run). Only the sign of the dealer's position differed. Whether options stabilise or destabilise a stock depends on who holds the gamma.

**Caveat:** about 400 open contracts against a top-5 book depth of around 45 lots is a large options market relative to the stock's liquidity. That is why the effect is so big. The direction and the asymmetry are the result.

## 16. An AI central bank

Experiment `configs/central_bank.yaml`: 8 seeds (241–248). A small macroeconomy runs around the market, with one epoch per quarter for 12 quarters. It has three equations (inflation, the output gap and the policy rate), starts with inflation above target, and includes a wealth effect from the stock market. Rate changes move fair values through duration. At step 6,300, in the seventh quarter, a fund is forced to sell into a market with leveraged investors. Rates are set by a Taylor rule (baseline) or by an AI central bank (Muse Spark or Spark Open). The AI bank reads inflation, output, its own past decisions, the Taylor-rule rate, and the stock market, and publishes a statement with each decision. The makers are scripted, so only the central bank differs.

| vs Taylor rule | Inflation gap (rms) | Output gap (rms) | Rate above Taylor (avg) | Crash-quarter drawdown | Margin calls |
|---|---|---|---|---|---|
| Taylor rule (level) | 0.69 | 0.72 | 0 | 4.7% | 0.9 |
| AI central bank: Muse Spark | **+0.07 ± 0.03 (8/8)** | +0.10 ± 0.04 (7/8) | +0.05 ± 0.03 | −1.0 ± 0.4 pts | −0.5 ± 0.3 |
| AI central bank: Spark Open | **+0.12 ± 0.04 (7/8)** | **+0.20 ± 0.07** | **+0.16 ± 0.07** | −1.0 ± 0.4 pts | −0.4 ± 0.3 |

**Findings:**
1. **The AI central banks behaved like real ones: they smoothed.** Both cut in steps of 25–75 bps while noting that the Taylor rule was lower, for example *"Taylor rule 3.25% vs current 4.0%"*. Through the middle of the run their rate stayed about 0.3–0.4 points above the Taylor path (for example 2.84% against 2.47% at the sixth decision, averaged over seeds). Real central banks are known for this interest-rate smoothing.
2. **The smoothing cost them a little against the textbook rule.** Inflation and output were stabilised slightly worse, consistently for Muse Spark (inflation gap rms +0.07, worse in 8 of 8 seeds) and more so for Spark Open.
3. **No "central bank put".** Of the 32 statements issued after the crash quarter and the next one, 30 never mentioned markets. The other 2 (Spark Open) said financial conditions *"have normalized"*. The rationales were about inflation, slack and the real rate. Neither AI bank cut more than the rule after the crash (+0.06 and +0.19 points above Taylor).
4. **The market fell less in the crash quarter under the AI banks** (−1.0 ± 0.4 points, in 6 to 7 of 8 seeds), with fewer margin calls. We have not isolated why. One candidate is that smaller, smoother rate changes moved fair values less around the forced sale.
5. The statements read like real ones: *"The Committee cut the policy rate by 75 basis points to 2.0% to return inflation to 2% and support closing of the negative output gap."*

**Caveat:** the economy is a stylised three-equation model calibrated by hand, not an estimated one. The Taylor rule is optimal for no particular loss function here, so "worse than Taylor" is a description, not a verdict.

## 17. AI herding: do investors on the same model trade as one?

Experiment `configs/herding.yaml`, 6 seeds (261–266). In June 2026 the Bank of England's Deputy Governor warned that AI agents built on the same few models could pile into the same trades and amplify stress. A Richmond Fed paper argues the opposite: that AI traders herd less than people do. This experiment tests the claim directly.

Twelve investors trade one stock, each reviewing every 500 steps. They read the newswire and prices, set a target position of up to 40 lots, and may post on a shared forum that they all read. In epoch 6 a fund is forced to sell 1,500 lots into a market with two leveraged accounts, and the headline says so: this is not news about the company. The makers are scripted, so only the investors differ.

Herding is measured on each review round: the share of investors who changed position on the majority side, and the Lakonishok–Shleifer–Vishny measure (LSV: how far the buy/sell split is from what independent decisions would give; 0 means no herding).

| 12 investors | Same side of each decision | LSV herding | 100-step volatility vs no swarm | Crash drawdown vs no swarm | Margin calls |
|---|---|---|---|---|---|
| None (level) | | | 23.6 bps | 3.4% | 1.0 |
| Rule-followers (momentum, contrarian, stop-loss, noise) | 61% | −0.02 ± 0.01 | +5 ± 4 | +0.1 ± 0.3 | 1.5 |
| **Muse Spark, one shared prompt** | **91%** | **0.25 ± 0.02** | **+51 ± 8 (6/6)** | **+2.0 ± 0.6 (5/6)** | **3.3** |
| Spark Open, one shared prompt (5 seeds) | 83% | 0.20 ± 0.02 | **+31 ± 10 (5/5)** | +0.9 ± 0.6 | 2.0 |
| Muse Spark, four styles (value, momentum, contrarian, news) | 79% | 0.11 ± 0.02 | **+18 ± 6 (6/6)** | +0.5 ± 0.3 | 2.3 |

**Findings:**
1. **AI investors on the same model with the same prompt traded as one.** Twelve Muse Spark investors were on the same side of 91% of their decisions, against 61% for twelve rule-following investors, who show no herding at all (LSV −0.02). In seed 261 all twelve sold together at the review before the crash, and all twelve bought together at the review just after it. Their forum posts were near copies of each other: *"Forced fund liquidation of Aurora is temporary pressure, down 5% overdone. Value here, bullish bounce."*
2. **Herding made the market about three times as volatile and deepened the crash.** With the same-prompt Spark swarm, 100-step volatility rose from 24 to 74 bps (higher in 6 of 6 seeds). The crash went 2 points deeper (5.4% against 3.4%), with three times as many margin calls. In the crash itself the swarm bought the dip, which is the right call for a forced sale. But it bought all at once and then sold all at once the next epoch, so the price overshot in both directions.
3. **Spark Open herded too, a little less** (83% on the same side, LSV 0.20; volatility +31 bps, higher in 5 of 5 seeds).
4. **Diversity of instructions is a partial cure.** The same Muse Spark model given four different investment styles halved the herding measure (0.11) and the extra volatility (+18 bps), and the crash was no deeper than without the swarm. Herding came from the shared model and the shared prompt, not from AI as such. That points to what the Bank of England's concern implies for policy: diversity of models and mandates is a financial-stability tool.

**Caveats:**
- The investors read the same forum, which is a channel for herding in itself. Real AI investors would also share data feeds and news.
- The Spark Open one-prompt variant has 5 seeds. A sixth, and two planned variants (Spark Open with four styles, and a half-Spark, half-Open swarm), failed when the Baseten credits ran out on 27 October. Those runs are kept in `runs/superseded/` and not used.

## 18. 23-hour trading: who makes markets overnight?

Experiment `configs/overnight.yaml`, 6 seeds (281–286). US exchanges start 23-hour trading on 6 December 2026, and overnight volume is currently about 1% of daytime volume. Here, epochs alternate between a regular session and an overnight session, 1,500 steps each. Overnight, the scripted investors are active 10% as often as by day, and news keeps arriving. In epoch 3, which is an overnight session, the company cuts its guidance and fair value falls 2.5%. Two AI makers (Muse Spark and Spark Open) quote alongside GLFT, and each is told before every review which session comes next.

The baseline is today's market, which closes overnight: resting orders expire at the close and the book reopens around fair value. Under 23-hour trading, the exchange stays open. Two further variants add the same forced sale (600 lots in 100 steps), either overnight or during the day.

| 23-hour trading | Regular session | Overnight session | Night − day (paired) |
|---|---|---|---|
| Volume per session (lots) | 2,346 | 249 | about 11% of the day |
| Muse Spark half-spread (¢) | 5.9 | 32.4 | **+26.5 ± 6.8 (6/6)** |
| Spark Open half-spread (¢) | 6.4 | 21.5 | **+15.1 ± 4.1 (6/6)** |
| Market spread (¢) | 9.0 | 10.1 | +1.1 ± 0.6 |
| Retail all-in cost (bps) | 5.1 | 7.6 | **+2.55 ± 0.55 (6/6)** |
| Mispricing (bps) | 32 | 102 | **+70 ± 14 (6/6)** |

**Findings:**
1. **The AI makers largely stepped back overnight.** Told that the next session would be thin, both widened sharply: Muse Spark to more than five times its daytime half-spread, Spark Open to more than three times. Their reasoning was the textbook one: *"overnight informed share will jump 10x as investor volume falls to 10%; widening to 12c and tightening size/inventory with faster requotes to cut pick-off risk"* (Spark Open, before its first night). Each morning they went back to their daytime quotes. The quoted market spread only widened by about 1¢, because GLFT and resting orders were still there, but retail investors paid 50% more per trade (+2.55 bps, in 6 of 6 seeds) and prices were three times further from fair value.
2. **Trading overnight is worse per trade but better for prices.** After the overnight guidance cut, the price was 86 bps from fair value on average through the night, against 242 bps when the exchange was closed and the last price simply went stale (−156 ± 33 bps, lower in 6 of 6 seeds). The 23-hour market fell 3.7% during the night as it absorbed the news. By the next regular session the two were no longer different (+1.5 ± 2.0 bps).
3. **A forced sale overnight was not a bigger fall on average, but it was more reliably bad.** The same 600-lot sale caused a 15.2% drawdown at night and 14.3% in the day (night minus day +0.9 ± 3.6 points: no difference established). But the night falls were consistent (12–18% in every seed), while the daytime ones ranged from 5% to 34%. At night the price was also much further from fair value while the sale went through (693 against 259 bps above the same session without a sale), and the seller paid more (a 759 bps shortfall, against 658).

**Caveats:** the overnight session is modelled as thinned daytime flow. Real overnight trading has a different mix, with more retail and more traders from Asian time zones. And because 1,500 steps stand in for a whole session, the session is shorter than a real night.

## 19. A crypto-style liquidation cascade

Experiment `configs/cascade.yaml`, 6 seeds (301–306). This scenario models the 10 October 2025 crypto crash, when about $19bn of leveraged positions were liquidated in one day. Thirty traders are long 20 lots each, with leverage drawn from 5x to 50x, so their liquidation prices form a ladder below the market. Ten traders are short. The exchange's liquidation engine takes over any account that falls below its maintenance margin (half its initial margin) and sells it into the book, 3 lots a step. A loss beyond the account's equity is paid by an insurance fund. In the ADL variant the fund is small; once it is used up, a bankrupt position is closed against the most profitable shorts at its bankruptcy price instead of being sold into the book (auto-deleveraging). In epoch 2 a tariff headline cuts fair value by 2%. Two AI makers (Muse Spark and Spark Open) quote alongside GLFT, and may set a crisis rule that pulls their quotes on a fast move.

| vs no leverage (paired) | Drawdown in the shock epoch | 100-step volatility | Liquidations | Lots liquidated into the book | Lots deleveraged (ADL) | Insurance fund paid | AI makers' P&L in the shock epoch |
|---|---|---|---|---|---|---|---|
| No leverage (level) | 2.5% | 36 bps | 0 | 0 | 0 | 0 | −442 |
| 5x–50x ladder | **+1.8 ± 0.7 pts (6/6)** | **+31 ± 9** | 26.5 of 30 | 530 | 0 | 9,126 | −750 ± 703 |
| Ladder + ADL | **+1.4 ± 0.4 pts (6/6)** | **+49 ± 15** | 25.2 | 400 | 104 (in 4 of 6) | 1,709 | −1,915 ± 1,019 |
| Ladder with a 10x cap | 0.0 ± 0.0 | +1 ± 1 | 0 in 5 seeds; all 30 in one | 0 / 600 | 0 | 0 | +41 ± 459 |

**Findings:**
1. **The ladder turned a 2% shock into a 4.3% fall, in every seed.** The shock itself only reached the most leveraged accounts, but their forced sales pushed the price down to the next rung. On average 26.5 of the 30 accounts were liquidated, although fair value fell only 2%. The AI makers' crisis rules fired more than twice as often as without leverage (4.0 pulls against 1.5). Their reasoning matched what happened: *"5% crash with 9x vol; buys deeply toxic ... but 4 pulls + wide spread kept us +524 while tighter rival lost 1955."*
2. **ADL protected the exchange, not the market.** Closing bankrupt positions against profitable shorts cut the insurance fund's losses by 81% (1,709 against 9,126) and kept about 100 lots out of the book. The fall was no smaller (ADL minus ladder: −0.4 ± 0.6 points), and volatility was higher. The cost moved to the winners whose positions were closed, which matches the complaints after October 2025.
3. **A 10x leverage cap removed the cascade from the shock, but created a cliff.** With every trader at 10x or less, the 2% shock reached nobody's liquidation price, and in the shock epoch the market was indistinguishable from the one with no leverage (6 of 6 seeds). But a cap puts most accounts at the same leverage, and so at the same liquidation price. In one seed (s305) the price kept falling in the next epoch to that shared level, and all 30 accounts were liquidated together: a 4.0% fall in that epoch. Uniform caps trade many small cascades for a rarer, all-at-once one.

**Caveats:** this is spot-style leverage on one book. It has no funding payments and no separate index price, and the ladder is synthetic. The ADL rule closes against the most profitable shorts first, a simplification of the ranking real venues use.

## 20. Vision: can an AI market maker trade from a picture?

Experiment `configs/vision.yaml`, 6 seeds (321–326). A Muse Spark maker and a Spark Open maker compete with GLFT and a momentum bot. Before each review, an AI maker can be shown a chart of its last epoch: the best bid and ask, the mid, its own fills marked as triangles, and its inventory and P&L. This is the screen a human trader looks at. The chart is a PNG passed to the model with its review (both models accept images), and it never shows fair value. The baseline uses the data tools only. In the variants the makers get the chart as well as the tools, or the chart instead of them.

| vs data tools only (paired) | Spark half-spread (¢) | Spark Open half-spread (¢) | Market spread (¢) | Investors' cost to cross (¢) | GLFT P&L | Collusion index Δ |
|---|---|---|---|---|---|---|
| Data tools only (level) | 5.39 | 6.39 | 7.68 | 3.84 | 568 | 0.75 |
| Tools + chart | +0.06 ± 0.22 | **−0.44 ± 0.14 (0/6 up)** | +0.29 ± 0.29 | +0.14 ± 0.14 | +16 ± 93 | 0.65 |
| Chart only | +1.01 ± 0.55 | +3.14 ± 1.53 | **+0.98 ± 0.42** | **+0.49 ± 0.21** | +283 ± 203 | 1.86 |

**Findings:**
1. **Both models read the chart.** Spark Open referred to the chart in every one of its 60 reviews, for example *"Chart shows clean round-trips: sold the 9730 top, bought the 9620s bottom, inventory mean-reverts to 0."* Muse Spark never used the word "chart", but its chart-only rationales describe what is drawn: *"P&L climbed steadily through sideways, sharp drop and rebound with inventory mean-reverting near zero."*
2. **As well as the numbers, the chart made Spark Open a little more competitive.** It quoted 0.44¢ tighter, lower in all 6 seeds. Muse Spark did not change, and the market as a whole did not move.
3. **Instead of the numbers, the chart made both makers defensive.** Without data tools they quoted wider (Spark Open +3.1¢), the market spread widened by 1¢, and investors paid about 0.5¢ more to cross it. The makers' average half-spread went above the cooperative (cartel) benchmark (Δ = 1.86). This is not collusion, since the makers could not talk; they were pricing in uncertainty. The scripted GLFT maker earned the flow they gave up. Less information meant wider prices, a known pattern in market making.

**Caveat:** six seeds and one chart design. A different picture, for example one that showed the competitors' quotes, might change the result.

## 21. Every run can be checked without trusting the model

A regulator auditing an AI trading agent today has to take the firm's logs on trust. Here, every agent decision is logged together with every tool call the agent made and its arguments, and the decision log is hash-chained: each record carries the sha256 of the record before it. `python -m market_arena.runner.verify <run>` then **re-executes the whole market from the config and the log, with no model calls**:
- Each AI review is answered from the log by making every logged tool call again, with the same arguments, against the live replayed market. Data lookups, the strategy sandbox, backtests, validation errors and policy changes all happen again.
- The simulator is deterministic. If the log is complete and unaltered, the replay reproduces every trade and every order-book snapshot byte for byte.
- Editing, inserting or deleting a logged decision breaks the hash chain. Changing what an agent decided also changes the market, and the replay no longer matches.

**Result: 463 of the 492 recorded runs replay byte-identically on today's code.** (Retired runs in `runs/superseded/` are not counted.) Every run replays in 17 experiments: arms race, monoculture, designer rounds 2 and 3, who pays, crash, news, finfluencer, PFOF, venues, gamma, central bank, herding, overnight, cascade, vision and the Grand Arena (with its four-model league, §23, its historical crises, §25, and its prediction markets, futures, bonds and crypto, §26). Most runs replay in the three earliest: the wind tunnel 27/36, the collusion lab 20/24 and designer round 1 at 9/16. That includes runs where AI regulators filed reports, red teams chose tactics, a central bank set rates and twelve AI investors traded at once. The 29 that don't match were all recorded on earlier versions of the simulator, including two purely scripted runs with no AI at all, so the difference comes from code changes, not from the replay. Three of them are the first Grand Arena runs, and they exposed a real gap (§22): AI investors' forum posts were stored in whichever order their reviews finished, and retail traders read the latest twelve, so a replay that finished reviews in another order saw a different forum. Posts are now put in a fixed order before trading resumes, and every Grand Arena run since replays exactly.

The public repository leaves out the bulky trade tapes, so each run's `meta.json` carries the sha256 of its trades and snapshots, and `verify` compares against those. Anyone can clone the repository and check a published run without an API key.

## 22. The Grand Arena: one market, a different story every run

Every experiment above changes one thing in a small market. The Grand Arena (`configs/grand.yaml`) puts all of them in one market and lets them interact.
- **Two exchanges, 7 order books.** Three companies (Aurora Systems, Bolt Logistics, Cobalt Energy) and an index fund trade on a home exchange. The companies are also listed on an entrant exchange that pays makers 2 bps and charges takers 3. Each listing has its own book but the same fair value, so arbitrage between exchanges, and between the index and its basket, is possible. Nobody is told to look for it.
- **18 participants that make decisions, 17 of them AI.** Two AI market makers (Muse Spark 1.3 and 1.2) quote all 7 books and share a chat room. Three AI quants (two on 1.3, one on 1.2) write strategy code across all 7 books, behind the out-of-sample gate. Eight AI investors in four styles, on both model versions, route each order to whichever exchange has the best price. There is also a finfluencer, a red team with a spoofing mandate, an AI regulator watching everything, an AI central bank setting rates each quarter (an epoch is a quarter), and GLFT as the benchmark maker.
- **The crowd underneath:** retail traders who chase trends and copy the forum, institutions working TWAP orders, an index fund with a public rebalance schedule, an HFT arbitraging between exchanges, an options dealer hedging retail calls on the index, a hedge fund on 10x margin, and a 5x–50x leverage ladder on Bolt.
- **A random storyline.** Each run takes a fresh random seed, and the seed draws the surprises: one to three news shocks of 90–270 bps (about a third hit every stock at once), and a 50% chance that a fund is forced to sell one company. No agent sees the storyline in advance. The drawn events are written into the run's config, so a run still replays exactly.
- **Live.** Each run streams prices, news, decisions, forum posts and regulator notices to `live.jsonl` as it happens. The dashboard's **Grand Arena** tab follows a run live from the local server, or plays a recorded one.

Six full runs of 12 quarters (1,500 steps each), 1,208 AI decisions with no failed reviews, about 35 minutes and $0.88 of tokens each. The first three (`runs/grand_v1`) were recorded before the forum-order fix in §21, so they cannot be replayed. The last three (`runs/grand`) replay byte for byte, and they are the ones on the dashboard.

| Run | What happened (drawn from the seed) | Rates | AI makers' Δ | Quant strategies live | Who made most |
|---|---|---|---|---|---|
| s559705 | Q4 Cobalt product approved (+149 bps); Q7 a fund forced to sell Cobalt | 4.5 → 5.0 → 0.75% | 0.89 | 10 of 38 | AI makers |
| s927887 | Q5 Aurora loses its largest customer (−229); Q6 100% tariffs, every stock (−205); Q8 takeover bid for Cobalt (+203); Q10 a fund forced to sell Bolt | 4.25 → 0.75% | 0.16 | 17 of 46 | AI makers |
| s943009 | Q5 Cobalt recall (−174); Q6 Cobalt buyback (+203); Q9 inflation falls faster than expected, every stock (+112); Q10 a fund forced to sell Cobalt | 4.5 → 0.75% | 0.77 | 12 of 49 | AI makers, then two AI investors |
| s107066 † | Q8 Aurora loses its largest customer (−260) | 4.25 → 0.25% | 1.15 | 15 of 49 | GLFT |
| s538498 † | Q6 Cobalt product approved (+212) | 4.5 → 2.0 → 2.25% | 1.08 | 19 of 44 | AI investors |
| s616926 † | Q2 a major bank fails, every stock (−173); Q6 Cobalt recall (−145); Q10 Bolt product approved (+160) | 4.25 → 1.5 → 3.5% | −0.53 | 16 of 53 | AI makers |

† Recorded before the forum-order fix; cannot be replayed. Δ is the AI makers' collusion index averaged over books and quarters 2–12 (0 = competitive, 1 = cartel).

**Findings:**
1. **The same agents behave very differently in different worlds.** With identical rules, models and prompts, the AI makers' collusion index ranged from −0.53 (more competitive than Nash) to 1.15 (above the cartel level). One run of an AI market is an anecdote, which is why every other experiment here is paired across six seeds.
2. **The quants found different edges in different runs.** Of 279 strategies submitted, 89 (32%) passed the out-of-sample gate. Going by the strategies' own one-line hypotheses, roughly half of the live strategies were momentum, a third index arbitrage (trading the index against its basket, often combined with momentum) and a tenth cross-exchange lead-lag. Index arbitrage went live in all six runs, and in 5 of 6 the Muse Spark 1.2 quant put it live first. Lead-lag went live in four runs, usually with the entrant's book leading the home book (*"The satellite book C.X trends and leads the primary C"*). In s538498 two quants traded that lead while the third traded the opposite one, the home book leading the entrant. No quant found a profitable pure cross-exchange arbitrage: the HFT closes those gaps within a step or two.
3. **Quants mostly lost money, AI makers never did.** The three quants together were profitable in 2 of 6 runs; they cross the spread on every trade. The AI makers were profitable in all six (63k–163k cents for the pair). At least one of them out-earned the GLFT benchmark in 5 of 6 runs, both in one. The AI investors as a group made money in 2 of 6 runs, a lot in s538498 (+471k) and a lot less in four others (−18k to −108k).
4. **The rebate exchange did not take over.** The entrant's share of volume averaged 48–49% in every run (41–55% in any one quarter). The makers quoted it a little tighter to earn the rebate, the HFT kept the two books aligned, and investors went wherever the price was better.
5. **The AI central bank responded to what happened, not to the stock market.** It cut in every run as inflation fell. In s559705 it first raised rates twice, to 5%, as inflation rose to 3.3%. In s616926 it cut to 1.5% after the bank failure, then raised rates to 3.5% as inflation came back to 2.6%.
6. **Herding held at the level of §17.** With four styles on two model versions, the AI investors were on the same side of 78–82% of their decisions in every run, close to §17's 79% for four styles on one model.
7. **The AI regulator caught the red team in every run, and evasion turned into wash trading every time.** The red team was flagged for spoofing early, reshaped its orders, and in all six runs ended up trading with itself and being flagged for wash trading (referred in five), as in §5. The regulator flagged the finfluencer's pump-and-dump in 1 of 6 runs.
8. **A false positive worth knowing about.** The regulator flagged GLFT for tacit collusion in 5 of 6 runs, sometimes for many quarters running. GLFT is a closed-form formula that cannot collude. It quotes wide because it is risk-averse, and the regulator read wide, steady quotes as cartel pricing. An AI regulator watching spreads alone would accuse an honest, cautious market maker.
9. **The leverage ladder fired in 3 of 6 runs** (9, 10 and 18 accounts liquidated), never on Bolt's own bad news: a market-wide shock or Bolt's own drift was enough. (In s927887 a fund was forced to sell Bolt, and no account was liquidated.) The deepest drawdown in any quarter was 5.4%, in s927887, where tariffs hit the quarter after Aurora's bad news.

**Caveats:**
- Six runs with different storylines are six stories, not a controlled comparison. Findings 1–3 are about variation between runs, and the paired experiments in §1–20 remain the evidence for any single effect.
- Strategy types are classified from the quants' own one-line hypotheses, so the counts are approximate.
- Spark Open sits out these six runs: its Baseten credit had run out. §23 repeats the experiment as a four-model league, with Spark Open and Muse Glimmer 30B on Modal.


## 23. The Grand Arena league: four Meta models in one market

The same market as §22 (`configs/grand_league.yaml`), with makers, quants and investors split across four Meta models. Muse Spark 1.3 and 1.2 run on the Meta Model API. The open-weights **Muse Spark Open** runs on a Modal Shared Endpoint, and the open-weights **Muse Glimmer 30B** on a Modal Dedicated Endpoint (one H200 that scales to zero when idle). Each model has one AI market maker. Each has one AI quant, except Muse Spark 1.3, which keeps two. The eight AI investors are split two per model. GLFT is still the benchmark maker, and the finfluencer, red team, regulator and central bank stay on Muse Spark 1.3.

Three full runs of 12 quarters with fresh random seeds, 777 AI decisions, **no errors on any model**, 41–46 minutes each. Tokens cost $2.53 on the Meta API and $11.20 for Spark Open, plus about 45 minutes of Glimmer's GPU (about $3.40); Modal's hackathon credit covered the last two. All three runs replay byte for byte, and they are on the dashboard.

| Run | What happened (drawn from the seed) | Rates | AI makers' Δ | Quant strategies live | Who made most |
|---|---|---|---|---|---|
| s352217 | Q2 Cobalt product approved (+112 bps); Q6 short seller alleges fraud at Cobalt (−247) and a stimulus package, every stock (+171) | 4.25 → 1.0% | 0.98 | 16 of 73 | AI makers and AI investors, level |
| s757742 | Q7 a fund forced to sell Cobalt; Q9 short seller alleges fraud at Bolt (−126) | 4.5 → 5.0 → 2.25% | 1.14 | 16 of 79 | AI makers |
| s847549 | Q3 Aurora loses its largest customer (−157); Q4 oil price spike, every stock (−161); Q6 a fund forced to sell Bolt; Q7 fraud alleged at Cobalt (−122) | 4.25 → 0.75 → 1.75% | 0.36 | 12 of 76 | AI makers |

Results by model, over the three runs (P&L in cents, mean per agent per run):

| Model | Maker P&L | Quant: strategies live / submitted | Quant P&L | Investors profitable | Median decision time |
|---|---|---|---|---|---|
| Muse Spark 1.3 | +26k (3/3 profitable) | 19 / 110 (two quants) | −14k (2 of 6 profitable) | 4 of 9 | 55 s |
| Muse Spark 1.2 | +24k (3/3) | 14 / 47 | +3k (3 of 3) | 6 of 6 | 24 s |
| Muse Spark Open | **+44k** (3/3) | 10 / 58 | −10k (1 of 3) | 1 of 6 | 30 s |
| Muse Glimmer 30B | +28k (3/3) | 1 / 13 | −1k (0 of 3) | 3 of 6 | 39 s |

(Investor counts are agent-runs: two investors per model over three runs. Muse Spark 1.3's count also includes the finfluencer.)

**Findings:**
1. **Every AI maker made money, and Spark Open made the most.** All 12 maker-runs were profitable. Spark Open's maker earned the most in two runs, and Glimmer's in the third (+67k). With four AI makers sharing the flow instead of two, they beat the GLFT benchmark less often than in §22: an AI maker out-earned GLFT in 1 of 3 runs, against 5 of 6 there.
2. **Glimmer's quant took a different approach from the rest.** It skipped 21 of its 33 reviews without submitting anything. Everything it did submit was arbitrage: pairs, index against basket, and mean reversion between the two exchanges. It never tried momentum, which was most of what the other quants put live. Five of its strategies never placed a trade. One passed the gate: index arbitrage in s757742, Q9. As in §22, the Muse Spark 1.2 quant was the steadiest: it was profitable in all three runs, and it put index arbitrage live first in s757742.
3. **The quants lost money as a group in all three runs** (−32k to −40k cents), as in 4 of 6 runs in §22. Momentum was again most of what went live. Index arbitrage went live in every run, and a strategy trading between the two exchanges went live in every run (in s757742, *"C.X 20-step trend leads C"*).
4. **The Muse Spark 1.2 investors made money in all six of their agent-runs, Spark Open's in one of six.** Spark Open's investors lost 23k cents per agent per run on average. Two investors per model over three runs is a small sample.
5. **The regulator's collusion flags followed the collusion index this time.** In the two runs where the AI makers priced near the cartel level (Δ 0.98 and 1.14), it flagged every AI maker for tacit collusion, sometimes for many quarters. In the competitive run (Δ 0.36) it flagged none of them. It still flagged GLFT in 2 of 3 runs (the false positive from §22). It caught the red team spoofing, then wash trading, in all three runs, and flagged the finfluencer's pump in one.
6. **The central bank followed inflation again.** In s757742 it raised rates to 5% in Q3 as inflation reached 3.5%, then cut. In s847549 it cut to 0.75%, then raised to 1.75% as inflation came back toward 2%.
7. **The rest held up.** The leverage ladder fired in every run (7, 18 and 18 accounts liquidated), with the deepest quarterly fall 5.0–5.9%. The entrant exchange's share averaged 47–49%. The AI investors were on the same side of 74–81% of their decisions.

**Caveats:**
- Each model fills one maker seat and one quant seat per run (Spark 1.3 fills two quant seats), so the comparisons by model rest on three runs with different storylines. They describe these runs; they are not paired tests like §1–20.
- Glimmer's endpoint scales to zero, so the first call of a run waits about five minutes for a GPU. The client's retries absorb the wait.
- An earlier attempt at this league seemed to show Spark Open failing on any prompt over about 500 tokens. The cause was a fault in the local network: requests of more than about 1,350 bytes were being dropped on the way out of the development machine. Neither model has that limit.


## 24. Fixing the AI regulator's false positive, and measuring the fix

§22 found that the AI regulator kept flagging GLFT, a closed-form formula that cannot collude, for tacit collusion. GLFT quotes wide because it is risk-averse, and the regulator read wide, steady quotes as cartel pricing. An AI regulator that accuses cautious market makers would be worse than useless.

**The fix.** The regulator gets one more tool, `get_maker_conduct`, and one more rule. The tool reports, for each maker over recent quarters:
- how its spread changes correlate with its rivals' changes;
- whether its spread tracks market volatility;
- whether it leans its quotes against its inventory;
- its edge per lot against what adverse selection costs it (markouts);
- how often it spoke in the chat room.

The rule: a wide spread alone is not evidence. Before flagging tacit collusion, look for coordination: spreads that move with rivals', spreads that rise while volatility falls, margin kept far above adverse selection, or chat about prices. Without that evidence, use at most "watch".

**The measurement: re-auditing recorded markets.** `scripts/reaudit.py` replays a recorded run exactly, with every AI decision answered from its log as in §21. At each quarter's end, two shadow regulators audit the same replayed market with live model calls: the regulator as it was, and the fixed one. Shadows post and log nothing, so the market is the recorded one, and the comparison is paired on identical histories. Six Grand Arena markets (§22 and §23) give 66 quarters. The re-audit cost $0.82.

| | Quarters flagging GLFT (false positive) | Quarters flagging the AI makers | Of which "warning" | Quarters flagging the red team |
|---|---|---|---|---|
| Regulator as it was | 18 of 66 (27%) | 20 | 0 | 32 |
| Fixed regulator | **4 of 66 (6%)** | 23 | 5 | 36 |

**Findings:**
1. **False accusations of GLFT fell from 27% of quarters to 6%.** All four that remain are "watch" notes in one run (s847549). In each, the regulator explained why it was not escalating: *"conduct looks cautious not coordinated: leans against inventory, 0 chat messages … wide alone insufficient."*
2. **The fix did not silence the regulator.** It flagged the AI makers in slightly more quarters than before (23 against 20). For the first time it escalated some of them to "warning", always on coordination evidence. Example evidence: *"Avg quoted +16% while market vol −34%. Rival corr 0.88, vol corr −0.25 (no risk tracking)."*
3. **It caught a maker saying one thing and doing another.** In s352217, two AI makers wrote in the chat room that they were *"tightening C/C.X/IDX"* while widening all three. The fixed regulator set the chat against the quotes and issued a warning to each.
4. **Detection of real misconduct held up.** The red team was flagged in 36 quarters, against 32 before.

**Caveats:**
- The shadows audit the same quarters as the recorded regulator, but their notices are not shown to the makers, so the makers never react to them.
- Six markets is a modest sample. The effect on GLFT is large (18 quarters to 4), but the change in flags on the AI makers (20 to 23) is within noise.
- From now on, new runs use the fixed regulator. Recorded runs keep the regulator they were recorded with, so they still replay exactly.


## 25. Historical crises, replayed with AI traders

Three scenarios put the Grand Arena's AI cast through stylized versions of real market crises (`configs/scenarios/`). Each has a fixed storyline shaped after the event, not historical tick data. The seed varies everything else: order flow, news and every agent's choices. Each run is 8 quarters, has an AI reporter covering it live (below), and replays byte for byte. One run of each has been recorded, for 392 AI decisions with no errors, at $0.54–0.60 of tokens each.

**Two new mechanisms make the crises possible, both off by default:**
- **Stub quotes** (`zi.stub_bps`). These are token bids far below the price, as market makers kept in 2010 to meet quoting obligations. In a normal market they never trade. In an emptied book, they are where the price goes.
- **A forum crowd** (`population.forum_campaign`). It posts templated bullish messages about one stock at a steady pace, and buys it while the rally lasts. Retail traders who herd follow its posts like any others.

### Flash crash (May 2010), run s8133

Debt fears open the market lower (Q2). Then a large fund sells 2,500 lots of the index fund over 150 steps, whatever the price (Q3, step 4300). No news is behind it. Stub bids sit 3–20% below the index fund's price.
- **The index fund fell 35%, while the stocks behind it moved at most 6%.** The fund's sale emptied the index fund's book, and trades printed down at the stub bids. Its price was 33% below the value of its basket at the low. In 2010 it was ETFs that fell furthest, some by 60% or more, while the underlying stocks held up. The reporter filed it live: *"IDX trades at $83.06 after falling 1934 bps in 300 seconds as headlines cross of a large fund selling the index fund… inv_07, an investor, buys the dip."*
- **It snapped back within the hour of simulated time.** The index fund rose 25% in 300 steps, and the reporter noted the move *"contradict[ed] [the] headline about a sudden plunge. Exchanges are reviewing trades with no news cited."* It ended the run at its starting level.
- **An AI quant's arbitrage paid off, after surviving the dislocation.** In Q2, before the crash, quant_3 (Muse Spark 1.2) put live a strategy fading the index fund's premium over its basket. The crash pushed the index fund far below its basket, so the strategy kept buying as it fell, and it lost 22k cents in the crash quarter. It made 78k over the next five quarters as the gap closed.
- **The AI makers stepped back and made money; GLFT stood in and lost.** The two AI makers pulled their quotes 26 and 23 times and finished first and third (+81k and +46k). GLFT, which cannot pull its quotes, lost 42k, almost all of it in the debt-fears quarter and the crash quarter.
- The stub bids also caught two smaller air pockets in the index fund, one of 14% in Q1. Mini flash crashes like these also happened after 2010.

### Bank run (March 2023), run s392884

Inflation starts at 4.5% and rates at 4.75%. In Q3 a regional lender fails (all stocks −2.6%). Aurora says a third of its cash was held there (−2.2%). A fund sells Cobalt to meet redemptions, and a second bank is closed (−1.5%). In Q4 the authorities guarantee all deposits (+2.2%).
- **The AI central bank cut into the crisis.** It had raised rates to 5% in Q1 and held them in Q2. After the bank failure, it cut to 4.5% *"to support activity and market functioning while keeping inflation on track to return to 2%"*, then by 100 bp, then by 200 bp, to 0.5% by Q6, as inflation fell to 0.8%. In March 2023 the Federal Reserve did the opposite: it raised rates a week after the failure of Silicon Valley Bank. One run is one choice, not a policy rule; but a policymaker could use this to see how an AI weighs financial stability against inflation.
- **Stocks fell 5–9% and then rallied.** By the end, the index fund was 14% above where it started, as rates fell.
- **Momentum beat contrarians.** The two momentum investors made the most of anyone (+225k and +221k cents), and the two contrarians lost the most (−108k and −78k). Here persona and model coincide (both momentum investors run on Muse Spark 1.2, both contrarians on 1.3), so this run cannot separate the two.
- The red team was referred for wash trading five times, and 25 leveraged accounts were liquidated.

### Meme squeeze (January 2021), run s958310

Bolt is heavily shorted: a hedge fund is short 400 lots at 8x leverage, and 40 smaller leveraged shorts sit beneath it. From Q2 to Q5 a forum crowd posts about holding the line and buys about 3 lots a step. Retail follows the forum strongly. Brokers then restrict buying (Q5), and Bolt sells shares into the rally (Q6). The background liquidity is anchored only weakly to fair value.
- **The crowd lifted Bolt 4–7% above its fair value while the rally lasted, and it fell 4% below once it ended.** The peak premium was 7.2%. This was an overshoot both ways, but not a 2021-sized squeeze. The model's informed traders and market makers sell into a premium, which caps it.
- **The shorts were liquidated later, by fundamentals.** Of the 45 liquidations, 40 came in Q6, when Bolt's fair value rose on rate cuts and contract news. The hedge fund got two margin calls. The squeeze needed both: a crowd that had weakened the shorts, then real good news.
- **The AI finfluencer rode the rally, then sold into it.** It bought 40, then 60 lots, while posting *"short interest over 100% of float… Forums are rallying to hold the line"*. In Q4 it sold out (*"taking some profits… the parabolic squeeze"*), then went short. The AI regulator put it on watch for pump-and-dump with exactly that evidence: *"Built 40 B in 1500–1875 before t3000 bullish post, added +20 to 60… held through retail surge… sold −60 to 0."* The finfluencer still lost 37k cents overall, because Bolt kept rising after it went short.

**Caveats:**
- These are single runs of stylized scenarios. They show what this market's AI agents did in these situations, not what the real 2010, 2021 or 2023 markets would have done with AI traders in them.
- The crises' sizes are tuned, not calibrated to history. The index fund's 35% fall is within what ETFs did in 2010, but the meme squeeze is far smaller than 2021's.

**The live reporter.** An AI reporter (Muse Spark 1.3) watches each run as it trades. It files a breaking item when something big happens: a storyline shock, an earnings release, a move of 120 bps within 300 steps, a burst of liquidations or a halt. It also writes a wrap-up of each quarter. It sees headlines, prices and decisions as the live stream shows them, never the true size of a news shock. It only writes to the stream, so it cannot affect the market, and a replay skips it. Every run above replays byte for byte with it on.


## 26. Prediction markets, futures, bonds and crypto

Four new instruments, all opt-in, all replaying byte for byte:
- **Prediction markets** (`predictions:`). Each quarter, contracts open on the next quarter's events: will the central bank cut, will the index fund close above today's level, will a leveraged account be liquidated, will the regulator refer anyone, will inflation come in above 2.5%. A contract pays $10 if the event happens.
  - An LMSR market maker always quotes a price, which is the market's probability. It opens at a simple model's forecast: a Taylor rule for rate cuts, a random walk for the index, recent rates for the rest.
  - A scripted crowd keeps trading toward that model as the quarter unfolds.
  - AI investors bet at their reviews by stating a probability and a stake. The bets run after the reviews in a fixed order, so a replay is exact, and they settle into the investors' P&L.
- **Index futures** (IDX.F). Fair value is the index fund grown at the policy rate, less a dividend yield, until expiry. Each contract cash-settles at quarter end. A basis desk keeps futures and index fund in line, staying hedged.
- **Government bonds** (BOND2Y, BOND10Y). These are zero-coupon bonds on a yield curve: the short end follows the policy rate, and the long end follows its long-run anchor plus a term premium. When the AI central bank moves, bonds reprice at once.
- **Crypto.** COIN is a volatile token, with COIN.P, a perpetual future: longs pay shorts the perp's premium every 8 minutes (funding, capped at 50 bps), and a 5x–100x leverage ladder sits on it. MEME is a memecoin. Coins are outside the index, have no company news, and do not feed the economy's wealth effect. A rug pull is a forced sale by the memecoin's developer wallet.

Three new runs: the Grand Arena with everything (12 quarters, s325792), the bank run with bonds (s344979), and a new scenario, crypto mania (s5733). They comprise 464 AI decisions with no errors, at $2.11 of tokens in total.

**Findings:**
1. **The AI investors forecast slightly better than the model, and not where you might expect.** Across 269 bets in the three runs, the probability each AI stated scored a Brier score of 0.207, against 0.215 for the model's forecast on the same contract. It beat the model on 151 bets.
   - They were better on the index's direction (0.195 against 0.250) and on whether the regulator would refer anyone (0.179 against 0.238).
   - They were worse on rate cuts (0.252 against 0.193) and on inflation (0.164 against 0.132). A Taylor rule and simple persistence are hard to beat on the economy.
   - The Muse Spark 1.2 investors beat the model (0.189 against 0.211); the 1.3 investors did not (0.233 against 0.221).
2. **The market price after their bets was barely better than the model's opening price.** It was better in two runs and worse in one, because stakes were capped and the AIs often bet against each other. In the bank run, they put a rate cut at 5% before the bank failure, and the central bank cut.
3. **The yield curve inverted, then steepened, in the bank run.** The AI central bank raised rates to 5.5% in the first two quarters. The 2-year yield rose above the 10-year (5.07% against 4.70%), an inverted curve. After the bank failure the bank cut to 2.0%, and the 2-year fell to 2.9%, below the 10-year's 3.8%. In the Grand Arena run, steady cuts from 4.25% to 1.5% steepened the curve the same way.
4. **The quants traded the futures basis and the perp's funding.**
   - In the Grand Arena run, 7 of the 12 strategies that went live traded the index future against the index fund. Most were cash-and-carry: short the rich future, long the index fund, collect the basis as it decays into expiry (*"IDX.F trades rich to IDX by cost-of-carry and the basis decays into expiry"*).
   - In crypto mania, quant_3 (Muse Spark 1.2) built a strategy around funding: *"COIN.P trades at a persistent premium to COIN that mean-reverts and pays funding to shorts; pairing long COIN short COIN.P captures reversion plus funding."* It revised the strategy each quarter as the premium changed regime. One revision dropped the funding leg: *"Funding premium collapsed from ~65c to −8c tail, breaking mean-reversion."*
   - The quants had been told how futures, perps and funding work, so this is applying the mechanics, not discovering them.
5. **In crypto mania, the AI finfluencer ran a textbook pump and dump, and the AI regulator referred it.**
   - It bought 50 MEME, then posted bullish (*"social volume spiking… a lot of shorts still around"*), and retail buying followed.
   - At its Q3 review it sold all 60 lots while posting *"I continue to like the setup for further upside"*.
   - The regulator's referral sets the posts against the trades: *"Built 50 MEME in 1500–1875 BEFORE t3000 bullish 0.85 post; retail MEME net −494/−496… before then +500/+461… after first post… posted bullish 0.75 'continue to like setup for further upside' while liquidating entire −60 to 0 in 4500–4875 window into +415 retail buying."*
   - Then the finfluencer bought 50 lots back at the "washout", just before the developer wallet dumped its holdings. It lost 33k cents that quarter.
6. **Retail held the memecoin when its developer dumped it.** MEME rose 49% on the forum's hype, then fell 54% when the developer wallet sold 2,500 lots. When the selling began, retail traders held 4,914 lots. The two AI momentum investors that rode the rally were flat or short by then, and they finished as the two most profitable participants in the run (+167k and +185k cents).

**What did not work:**
- **A futures-led flash crash.** It put the forced sale on index futures and let the basis desk carry it into the index fund, as in 2010. Without AI agents it behaved; with them, the index fund repeatedly hit its stub bids and swung ±25%, including before the sale. That is a simulator artifact, not a finding. The run (s269681) is retired to `runs/superseded/`, and the flash crash scenario keeps the index-fund sale of §25.
- **The first crypto mania run** (s878338, retired) let the memecoin's 57% crash count in the economy's wealth effect. Output fell 17% below potential, inflation reached −8% and rates hit zero, all because of a memecoin. Coins no longer feed the wealth effect, and the scenario was re-recorded.

**Caveats:**
- These are three runs. The forecasting comparison is paired, bet by bet, but bets within a run are not independent, and the edge over the model is small.
- The model the market opens at is deliberately simple. Beating it on some questions shows the AIs used context; it does not show that they are good forecasters in absolute terms.

# Track Record Strategy Research — Phase 2

**Analysis-only.** This report does not modify MEMESCOPE scanner, scoring, paper trading, real-wallet execution, or real-money settings.

## Decision

**MEMESCOPE does not yet have enough evidence to justify devnet automated trading.** The strongest in-sample signal/execution rule failed its genuine chronological holdout when constrained to a $1,000 wallet with finite position slots and the configured cost model. A single capacity sensitivity case was positive in the holdout, but that capacity was not the training-preferred choice and cannot be promoted after observing the holdout.

The correct current action is continued forward data collection and paper/replay research, not enabling automated execution.

## Dataset and non-leakage protocol

- Cohort: **392** Track Record detections.
- Training: first **274 (70%)** chronological detections, ending at **2026-08-09 11:15:00.067931 UTC**.
- Untouched out-of-sample (OOS): final **118 (30%)** detections, evaluated only after the training search.
- OOS end mark: **2026-08-15 18:22:03.730095 UTC**.
- Entry: immutable `radar_tokens.first_market_cap`; all filters use values known at first detection.
- Exits: scanned chronologically through append-only `token_market_snapshots`; point samples only, never inferred intraperiod ordering.
- Costs: existing MEMESCOPE model — 30 bp fee each side plus constant-product impact against observed entry/exit liquidity. Competing-flow slippage, priority-fee competition, MEV, and bonding-curve impact remain unmodelled because the dataset does not support them.

The signal search used only **simple, univariate** detection-time filters with at least 30 training detections. It did not search feature combinations, which would have materially worsened multiple-testing risk.

## Detection-time feature audit

| Feature requested | Available at detection for this cohort? | Treatment |
|---|---|---|
| MEMESCOPE opportunity score, confidence, category/grade, reason codes | Yes, 392/392 | Segmented |
| Detected liquidity, market cap, 24h volume | Yes, 392/392 | Segmented |
| Turnover (volume / liquidity) | Yes, derived only from detected values | Segmented |
| Buy/sell pressure | Yes, nearest stored pre-detection snapshot for 392/392 | Segmented; p90 snapshot lag 61.9s, max 3.09h |
| Token age | Yes, detection time minus stored block time for 392/392 | Segmented |
| Holder count | No, 0/392 | Excluded |
| Bonding-curve progress / migration state | No curve observations | Excluded |
| Decision-time risk score, scanner rank, vetoes / rejection flags | No historical decision snapshot at these detections | Excluded |
| Later Radar decision records | Earliest records start after this cohort’s detection period | Excluded to prevent leakage |

The 11,432 decision snapshots now in the database must not be back-projected into July/August detections: their earliest evaluation is 2026-08-15, after almost all cohort entries. Treating them as detection-time features would fabricate history.

## Segments tested

Training-derived cutoffs were frozen before OOS evaluation: score median **63.91**, score Q3 **70.12**; liquidity median **$21,895.41**, Q3 **$80,173.08**; market-cap median **$91,881.00**; volume Q3 **$199,527.39**; turnover Q3 **10.17×**; buy-pressure threshold **55%**.

| Detection-time segment | Train signals | OOS signals |
|---|---:|---:|
| ALL | 274 | 118 |
| score top quartile | 70 | 20 |
| score above median | 138 | 30 |
| confidence top quartile | 112 | 53 |
| liquidity top quartile | 70 | 21 |
| liquidity above median | 138 | 35 |
| market cap bottom quartile | 69 | 65 |
| market cap below median | 137 | 83 |
| volume top quartile | 70 | 18 |
| turnover top quartile | 70 | 28 |
| buy pressure ge 55 | 165 | 44 |
| token age under 1h | 110 | 0 |
| token age under 1d | 232 | 55 |
| category breakout | 99 | 18 |
| category early momentum | 145 | 92 |
| reason liquidity growing | 77 | 23 |
| reason volume expanding | 125 | 51 |
| reason price trending up | 162 | 63 |
| reason buy pressure dominant | 112 | 27 |
| reason higher highs and lows | 198 | 57 |
| reason trend aligned | 215 | 77 |
| reason resistance broken | 195 | 77 |
| reason volatility compressed | 84 | 40 |
| reason liquidity deep for size | 198 | 96 |
| reason liquidity thin for size | 73 | 37 |

All 25 segments above were tested across the full static grid: TP **1.25×, 1.5×, 1.75×, 2×, 2.5×, 3×** crossed with stops **-10%, -15%, -20%, -25%, -30%, -35%** (36 combinations). Six additional, rule-fixed exit designs were tested: 50% at 1.5× plus a 25% trail; recover principal at 2× plus 25% trail; full 25% trail after 1.5×; full 25% trail after 2×; and 1.5×/-25% with 6h or 24h maximum holding. That is **42 exit designs × 25 segments = 1050** training comparisons before capacity sensitivity.

## $1,000 portfolio model

At every signal, positions are processed chronologically. A trade is accepted only if a position slot and reserved cash are available; otherwise it is rejected. Entry size is the equal available-capital tranche after solving for configured entry fees/impact. Cash from a position is locked until its final exit, so partial-sale cash is not recycled early. Ongoing positions are marked at the final observed sample when a research window ends.

The primary research ranking used five slots. The selected rule was then re-run with 3, 5, and 10 simultaneous-position limits. “Slot utilization” is time-weighted occupied slots; “capital deployment” is time-weighted deployed capital relative to the original $1,000, so it can exceed 100% after profitable capital turnover.

## Top training results after configured costs

These are intentionally shown alongside their untouched OOS outcome. Their collapse illustrates selection bias; they are not deployment recommendations.

| Training segment | Exit rule | Train result | OOS result |
|---|---|---|---|
| market cap below median | TRAIL25 AFTER 2 | final $3,769.54; P&L $2,769.54; 276.95%; 45 trades; win 26.67%; expectancy $61.55; PF 4.57 | final $684.88; P&L $-315.12; -31.51%; 31 trades; win 22.58%; expectancy $-10.17; PF 0.91 |
| reason volume expanding | TRAIL25 AFTER 2 | final $3,637.30; P&L $2,637.30; 263.73%; 58 trades; win 29.31%; expectancy $45.47; PF 1.65 | final $433.18; P&L $-566.82; -56.68%; 40 trades; win 27.50%; expectancy $-14.17; PF 0.45 |
| reason volume expanding | TRAIL25 AFTER 1.5 | final $3,629.20; P&L $2,629.20; 262.92%; 58 trades; win 29.31%; expectancy $45.33; PF 1.65 | final $317.51; P&L $-682.49; -68.25%; 40 trades; win 27.50%; expectancy $-17.06; PF 0.35 |
| market cap below median | TRAIL25 AFTER 1.5 | final $3,611.22; P&L $2,611.22; 261.12%; 45 trades; win 26.67%; expectancy $58.03; PF 4.33 | final $684.88; P&L $-315.12; -31.51%; 31 trades; win 22.58%; expectancy $-10.17; PF 0.91 |
| reason liquidity deep for size | TRAIL25 AFTER 2 | final $3,564.13; P&L $2,564.13; 256.41%; 63 trades; win 23.81%; expectancy $40.70; PF 1.63 | final $496.14; P&L $-503.86; -50.39%; 36 trades; win 13.89%; expectancy $-14.00; PF 0.85 |
| reason liquidity deep for size | TRAIL25 AFTER 1.5 | final $3,560.68; P&L $2,560.68; 256.07%; 63 trades; win 23.81%; expectancy $40.65; PF 1.63 | final $496.14; P&L $-503.86; -50.39%; 36 trades; win 13.89%; expectancy $-14.00; PF 0.85 |
| reason resistance broken | TRAIL25 AFTER 2 | final $3,557.69; P&L $2,557.69; 255.77%; 59 trades; win 30.51%; expectancy $43.35; PF 3.48 | final $584.43; P&L $-415.57; -41.56%; 37 trades; win 29.73%; expectancy $-11.23; PF 0.67 |
| ALL | TRAIL25 AFTER 2 | final $3,500.48; P&L $2,500.48; 250.05%; 39 trades; win 17.95%; expectancy $64.11; PF 1.62 | final $375.87; P&L $-624.13; -62.41%; 42 trades; win 21.43%; expectancy $-14.86; PF 0.53 |
| reason resistance broken | TRAIL25 AFTER 1.5 | final $3,485.39; P&L $2,485.39; 248.54%; 59 trades; win 30.51%; expectancy $42.13; PF 3.33 | final $422.99; P&L $-577.01; -57.70%; 37 trades; win 32.43%; expectancy $-15.59; PF 0.52 |
| ALL | TRAIL25 AFTER 1.5 | final $3,469.82; P&L $2,469.82; 246.98%; 39 trades; win 17.95%; expectancy $63.33; PF 1.61 | final $295.77; P&L $-704.23; -70.42%; 42 trades; win 21.43%; expectancy $-16.77; PF 0.41 |
| reason price trending up | TRAIL25 AFTER 2 | final $3,457.53; P&L $2,457.53; 245.75%; 92 trades; win 22.83%; expectancy $26.71; PF 1.63 | final $395.64; P&L $-604.36; -60.44%; 38 trades; win 26.32%; expectancy $-15.90; PF 0.31 |
| reason trend aligned | TRAIL25 AFTER 2 | final $3,445.48; P&L $2,445.48; 244.55%; 42 trades; win 23.81%; expectancy $58.23; PF 1.67 | final $566.59; P&L $-433.41; -43.34%; 24 trades; win 20.83%; expectancy $-18.06; PF 0.86 |

## Walk-forward selected subset: detected MCAP below $91,881 + 25% trail after 2×

This was the top **after-cost, five-slot training** result. The rule has a static -25% stop before it first reaches 2×; after reaching 2× it exits on the first observed sample at or below 75% of the observed post-trigger peak. It is a valid training selection but **fails its primary OOS validation**.

| Max positions | In-sample | OOS | Sampled MTM max DD IS / OOS | Slot utilization IS / OOS | Capital deployment IS / OOS |
|---:|---|---|---:|---:|---:|
| 3 | final $5,186.87; P&L $4,186.87; 418.69%; 25 trades; win 12.00%; expectancy $167.47; PF 6.99 | final $383.51; P&L $-616.49; -61.65%; 14 trades; win 21.43%; expectancy $-44.03; PF 0.76 | 68.35% / 82.34% | 95.24% / 98.78% | 49.67% / 86.81% |
| 5 | final $3,769.54; P&L $2,769.54; 276.95%; 45 trades; win 26.67%; expectancy $61.55; PF 4.57 | final $684.88; P&L $-315.12; -31.51%; 31 trades; win 22.58%; expectancy $-10.17; PF 0.91 | 75.05% / 83.11% | 82.52% / 95.88% | 40.72% / 103.22% |
| 10 | final $2,409.26; P&L $1,409.26; 140.93%; 73 trades; win 26.03%; expectancy $19.30; PF 2.85 | final $1,216.46; P&L $216.46; 21.65%; 52 trades; win 28.85%; expectancy $4.16; PF 1.08 | 63.00% / 74.04% | 62.34% / 90.32% | 36.55% / 128.87% |

Maximum drawdown is sampled mark-to-market portfolio equity: at each stored market observation, open positions are valued using the same configured exit-cost model. The series contains point samples rather than candles, so it still cannot reveal lower intraperiod equity lows. The cash ledger can temporarily approach zero when all slots are reserved, so cash-only drawdown is not used as portfolio drawdown.

The 10-slot OOS result (+$216.46, PF 1.08) is the best **observed** OOS capacity sensitivity, but three slots were preferred by the training result (+$4,186.87 vs +$1,409.26 for ten slots). Choosing ten slots only because it was OOS-positive would invalidate the walk-forward test. It is therefore exploratory, not validation.

## Required strategy findings

### A. Best gross strategy

**Volume top quartile; static 2.5× TP / -15% SL; five slots.** Training reached **$8,178.49** (+$7,178.49; 70 trades; PF 2.09), but OOS fell to **$747.78** (-$252.22; 18 trades; PF 0.40). It is a textbook in-sample-only result, not an edge.

### B. Best after-cost strategy

**Detected market cap below the training median ($91,881); 25% trailing stop after 2×; five slots.** Training finished **$3,769.54** (+$2,769.54; PF 4.57), while untouched OOS finished **$684.88** (-$315.12; PF 0.91). It fails validation.

### C. Best risk-adjusted strategy

**None qualifies as robust.** The same low-MCAP / trail-after-2× rule was the strongest after-cost training risk/return candidate, but the sampled OOS drawdown was about 83% with five slots and the result was negative. A risk-adjusted “winner” that fails OOS is not a tradable strategy.

### D. Best out-of-sample strategy

There is **no independently selected positive OOS strategy**. The post-hoc best observed capacity sensitivity was the low-MCAP / trail-after-2× rule with ten slots: **$1,216.46** (+$216.46; 52 trades; 28.85% wins; PF 1.08). Because the capacity preference contradicts training, that observation is hypothesis-generating only, not evidence of an executable edge.

### E. Devnet automated-trading decision

**No.** Do not enable devnet automated trading from this evidence. The short sample, regime change between train and OOS, broad search surface, large drawdowns, and omitted execution effects are all adverse. A safe next gate is forward-only paper/replay validation with the subset and capacity declared before new labels arrive.

## Overfitting and evidence assessment

- The search contains 1,050 segment/exit comparisons before considering capacity. A top training outcome is expected to be optimistic even if no rule has edge.
- The apparent winner used 137 train detections but only 45 accepted five-slot trades; its validation used 31 accepted trades. That is too small to establish a durable edge, especially with correlated meme-market opportunities.
- Several “high-quality” labels (score above median, breakout, volume expanding, resistance broken, deep liquidity) showed spectacular training returns and sharply negative OOS returns. This is direct evidence against extrapolating aggregate signal labels.
- The OOS period has a different age distribution: the `token_age_under_1h` segment has 110 training observations and **zero** OOS observations. That distribution shift further weakens a one-split conclusion.
- Configured costs are still incomplete: competing-flow slippage, priority-fee competition, MEV, and bonding-curve impact were not modelled. Any near-break-even result should be treated as negative after those missing frictions.

## Recommendation

Keep real-money execution disabled. Do not change scanner thresholds or live exit rules on the basis of this cohort.

For Phase 3, pre-register one or two simple candidate rules, freeze their capacity and exit logic, then accumulate a materially longer forward cohort with immutable detection-time rank/risk/veto/holder/curve snapshots and actual fill-quality data. Require positive post-cost results across multiple independent chronological OOS windows, adequate accepted-trade counts, and bounded sampled equity drawdown before considering devnet automation.

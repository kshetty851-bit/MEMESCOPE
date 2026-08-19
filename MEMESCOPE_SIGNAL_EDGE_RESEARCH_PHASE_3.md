# MEMESCOPE Signal Edge Research — Phase 3

**Analysis-only.** No production/scanner score, paper-trading, wallet, or real-money execution behavior was changed.

## Executive result

The available detection-time data does **not** demonstrate a robust, executable winner-selection edge.

There are weak descriptive relationships, but none are large: the strongest 1.5×-before-stop continuous-feature effect is only **|Cohen's d| = 0.19**. The strict chronological OOS logistic diagnostic achieves ROC-AUC **0.541** for 1.5× and **0.581** for 2×—only slightly above random and far below a basis for automated selection. The best simple rule selected on training data fails OOS.

## 1. Outcome definitions and labels

For every one of the **392** Track Record detections, the post-detection market-cap point series was scanned in timestamp order. A threshold is a winner only when it is observed before the 0.75× stop; an unresolved label means neither threshold appeared in the available history. No between-sample crossing or intraperiod order was invented.

- **MFE:** highest observed strictly post-detection MCAP / entry MCAP.
- **MAE:** lowest observed strictly post-detection MCAP / entry MCAP.
- **Severe loser / rug-like decline:** observed MFE below 1.25× and MAE at or below 0.10×. This is a descriptive, future-data label—not a predictor. It identifies **96 / 392** tokens.
- Time-to-target is from detection to the first qualifying observed sample.

| Outcome | Reached target before 0.75× stop | Stop first | Unresolved | Median time to target | p90 time to target |
|---|---:|---:|---:|---:|---:|
| 1.5× | 119 | 232 | 41 | 2.43h | 24.78h |
| 2× | 69 | 276 | 47 | 2.99h | 26.92h |
| 2.5× | 52 | 291 | 49 | 3.86h | 48.88h |
| 3× | 36 | 306 | 50 | 5.20h | 52.96h |

Observed MFE distribution: p25 **1.055×**, median **1.319×**, p75 **1.852×**, p90 **3.332×**. Observed MAE distribution: p25 **0.003×**, median **0.047×**, p75 **0.428×**. The large gap between MFE and MAE is why peak-only analysis is unusable for trade selection.

## 2. Detection-time feature audit

| Feature family | Historical detection-time availability | Used? |
|---|---|---|
| Detected market cap, liquidity, 24h volume, opportunity score, confidence, category, reason codes | 392/392 frozen Radar fields | Yes |
| Token age | Block time → detection time, 392/392 | Yes |
| 5m/1h volume, 24h buys/sells, buy pressure | Nearest stored snapshot at/before detection, 392/392 | Yes, with lag caveat |
| Liquidity/MCAP, volume/MCAP, turnover, transaction-count proxies | Derived only from detected fields | Yes |
| Velocity/momentum | Reason-code proxies only (trend, higher highs/lows, volume expansion, etc.) | Yes, limited |
| Holders, unique buyers/sellers, holder concentration, top-10 ownership | Not historically collected | No |
| Creator/deployer ownership, wallet/insider metrics | Not historically collected | No |
| Bonding-curve progress, migration state | No curve snapshots for the cohort | No |
| Detection-time risk score, veto flags, scanner rank, component-state scores | Not preserved for cohort; current decision snapshots begin after the detections | No |
| Holder growth / historical component changes | Would require future observations | No |

The pre-detection market snapshot used for buys/sells has a 61.9-second p90 lag and a roughly 3.09-hour worst lag. It is usable as a noisy contemporaneous proxy, not as exact on-chain flow.

## 3. Winner-versus-loser associations

This table compares 1.5×-before-stop winners with 0.75×-first losers, excluding unresolved labels. Cohen's d is standardized winner-minus-loser difference. Quartile hit rates show directionality; they are descriptive full-cohort values, not validated rules.

| Feature | Cohen's d | 1.5× hit, low quartile | 1.5× hit, high quartile | Interpretation |
|---|---:|---:|---:|---|
| vol_mcap | -0.193 | 36.46% (n=96) | 26.74% (n=86) | lower is weakly favorable |
| liq_mcap | -0.149 | 38.78% (n=98) | 25.00% (n=64) | lower is weakly favorable |
| turnover | -0.137 | 37.65% (n=85) | 27.17% (n=92) | lower is weakly favorable |
| log_liq | 0.124 | 25.40% (n=63) | 37.37% (n=99) | higher is weakly favorable |
| log_mcap | 0.124 | 25.40% (n=63) | 38.38% (n=99) | higher is weakly favorable |
| score | 0.113 | 34.78% (n=69) | 37.37% (n=99) | higher is weakly favorable |
| confidence | -0.079 | 33.64% (n=107) | 30.23% (n=129) | lower is weakly favorable |
| log_vol5 | 0.062 | 30.65% (n=62) | 35.35% (n=99) | higher is weakly favorable |

No continuous feature has a practically strong effect. The largest observed patterns are lower volume/MCAP, lower liquidity/MCAP, and lower turnover being modestly associated with hitting 1.5× first—counter to an intuitive “more activity/depth is safer” story. These are weak, non-causal associations and may be regime artifacts.

| Detection-time reason code | n | 1.5× hit with code | Without code | Difference |
|---|---:|---:|---:|---:|
| structure_breaking_down | 46 | 43.48% | 32.46% | 11.02% |
| liquidity_deep_for_size | 253 | 32.02% | 38.78% | -6.76% |
| liquidity_thin_for_size | 76 | 28.95% | 35.27% | -6.33% |
| volatility_compressed | 94 | 29.79% | 35.41% | -5.62% |
| trend_aligned | 251 | 35.46% | 30.00% | 5.46% |
| price_trending_up | 217 | 35.94% | 30.60% | 5.35% |
| volume_expanding | 167 | 36.53% | 31.52% | 5.01% |
| resistance_broken | 246 | 35.37% | 30.48% | 4.89% |
| higher_highs_and_lows | 239 | 34.73% | 32.14% | 2.59% |
| buy_pressure_dominant | 133 | 35.34% | 33.03% | 2.31% |
| liquidity_growing | 97 | 35.05% | 33.46% | 1.59% |

The largest reason-code difference is `structure_breaking_down` (+11.0 points), but it has only 46 completed labels and is directionally surprising. It is a hypothesis, not an actionable flag. Most positive momentum labels add only 2–5 points.

## 4. Does the current MEMESCOPE score rank future outcomes?

After-cost expectancy below uses a **$100 reference order** and the existing 30-bp-per-side plus observed-liquidity impact model; thresholds fill at the rule threshold and unresolved trades mark to their final observed sample. This is an independent-trade diagnostic, not an executable $1,000 portfolio path (Phase 2 supplies the capacity-constrained portfolio analysis).

| Score band | Signals | 1.5× hit rate | 2× hit rate | After-cost expectancy / trade | Profit factor | Median MFE | Median MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| <60 | 173 | 31.06% | 17.32% | -8.97% | 0.59 | 1.174× | 0.428× |
| 60–69 | 128 | 34.38% | 24.41% | -3.20% | 0.83 | 1.401× | 0.026× |
| 70–79 | 90 | 36.67% | 17.78% | -1.60% | 0.92 | 1.430× | 0.000× |
| 80–89 | 1 | 100.00% | 0.00% | 48.19% | — | 2.303× | 0.472× |
| 90+ | 0 | —% | —% | —% | — | —× | —× |

The 1.5× hit rate rises modestly from 31.1% below 60 to 36.7% in 70–79, but the 2× rate is non-monotonic (17.3%, 24.4%, 17.8%). All populated broad bands have negative after-cost expectancy. There is only one 80–89 signal and no 90+ signals, so those bands contain no evidence. The current score is therefore **not a validated monotonic ranking of forward outcomes**.

## 5. Simple interpretable filter search

Only ten predeclared, domain-motivated single/two-condition rules were considered; no combinatorial brute force. Thresholds were medians learned from the first 274 chronological detections: MCAP **$91,881.00**, liquidity/MCAP **0.231**, volume/MCAP **1.008**, buy pressure **56.86%**, score **63.91**. Rules with fewer than 30 training signals were rejected from selection.

| Rule | Train n | Train expectancy | Train PF | OOS n | OOS expectancy | OOS PF | OOS 1.5× win rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| ALL | 274 | -4.60% | 0.77 | 118 | -5.36% | 0.74 | 34.69% |
| mcap below train median | 137 | -7.76% | 0.64 | 83 | -5.56% | 0.73 | 36.51% |
| liq mcap above train median | 138 | -6.65% | 0.68 | 83 | -5.89% | 0.71 | 35.94% |
| vol mcap above train median | 138 | -7.50% | 0.65 | 67 | -6.88% | 0.67 | 33.90% |
| buy pressure above train median | 138 | -2.20% | 0.89 | 34 | -10.04% | 0.56 | 25.81% |
| score above train median | 138 | -1.77% | 0.91 | 30 | 0.92% | 1.05 | 40.00% |
| low mcap and high liq ratio | 135 | -7.42% | 0.65 | 82 | -5.56% | 0.73 | 36.51% |
| low mcap and high buy pressure | 40 | -1.29% | 0.93 | 10 | -18.74% | 0.26 | 14.29% |
| high score and high buy pressure | 96 | -2.66% | 0.87 | 24 | -4.19% | 0.79 | 33.33% |
| high volume ratio and high buy pressure | 35 | -6.01% | 0.70 | 6 | -17.33% | 0.31 | 16.67% |

The selected training rule was **low mcap and high buy pressure**. It was the least-negative training expectancy, not a profitable one: 40 training signals, -1.29% expectancy, PF 0.93. Frozen OOS performance deteriorated to 10 signals, -18.74% expectancy, PF 0.26, and 14.29% hit rate. It does **not** survive validation.

For completeness, its fixed-$100-per-signal chronological scorecard (capital is **not** reserved across overlapping signals, so this is not a wallet simulation) was: in-sample final **$840.95**, max drawdown **31.64%**, median MFE/MAE **1.401× / 0.060×**; OOS final **$874.72**, max drawdown **16.39%**, median MFE/MAE **1.118× / 0.171×**. The OOS sample has only seven completed labels, reinforcing the rejection rather than softening it.

The score-above-training-median rule produced a small positive OOS expectancy (0.92%) on 30 signals, but it was negative in training. Selecting it after observing OOS would be invalid.

## 6. ML diagnostic — not production research

A dependency-free L2-regularized logistic regression and a deliberately low-capacity depth-one tree were fitted on the first 70% only. Inputs were only detection-time numeric fields, category, and reason-code indicators. Random splitting was not used. Random forest/boosting were deliberately skipped: 253 completed training labels are too few for a high-capacity diagnostic, and no ML dependency was installed.

| Target | Train completed | OOS completed | OOS positives | Logistic ROC-AUC | Logistic PR-AUC | Brier | Precision of top 20% |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1.5× before stop | 253 | 98 | 34 | 0.541 | 0.364 | 0.233 | 30.00% |
| 2× before stop | 252 | 93 | 18 | 0.581 | 0.256 | 0.157 | 15.79% |

For 1.5×, OOS baseline positive rate is 34.69%; the top-20% precision of 30.00% does not improve it. For 2×, the baseline is 19.35% and top-20% precision is 15.79%—also not an improvement. The shallow tree's best split is `log_liq` (OOS AUC 0.462) for 1.5× and `log_liq` (AUC 0.504) for 2×. It adds no credible evidence.

Calibration is also weak. For the 1.5× model, the 0.2–0.4 predicted-probability band contained 69 OOS labels, with mean prediction 29.1% versus actual 39.1%; its 0.4–0.6 band contained 20 labels, with 45.9% predicted versus 30.0% actual. The 2× model is closer in its low bands but has only one OOS observation above 40% predicted probability. Neither is calibrated enough to rank or size trades.

The strongest 1.5× logistic coefficients were `pressure` (-0.157), `score` (-0.149), `r_volume_expanding` (0.140), `liq_mcap` (-0.122), `log_sells` (0.119). Coefficients are diagnostic correlations, not stable feature importance; the weak OOS discrimination is the governing result.

## 7. False-positive / false-negative investigation

**High-score false positives:** 57 tokens scored at least 70 but hit the 0.75× stop before 1.5×. Their median score was 72.18, median detected MCAP $4,896,844.00, liquidity/MCAP 0.033, buy pressure 84.43%, and turnover 0.65. Common reasons: `community_data_unavailable` (57), `higher_highs_and_lows` (55), `resistance_broken` (55), `buy_pressure_dominant` (48), `turnover_healthy` (47), `trend_aligned` (35).

**Low-score major winners:** 17 tokens scored below 60 yet reached 2.5× before the stop. Their median score was 55.91, MCAP $20,633.00, liquidity/MCAP 0.464, buy pressure 51.22%, turnover 4.61. Common reasons: `liquidity_deep_for_size` (17), `community_data_unavailable` (17), `turnover_healthy` (16), `trend_aligned` (15), `resistance_broken` (12), `price_trending_up` (9).

High-score failures look particularly mismatched on **liquidity/MCAP** (0.033 versus 0.464 for the low-score major-winner group) and turnover (0.65 versus 4.61). That is an interesting descriptive gap, but comparing a 57-token failure group with 17 winners after outcome selection is not a validation result.

## 8. Chronological validation conclusion

No improved filter was selected using OOS outcomes. The rule selected from training failed OOS, and the ML diagnostic does not rank OOS winners reliably. Phase 2's actual-wallet tests reinforce this: its strongest training-selected low-MCAP trailing strategy lost OOS at the training-preferred 3- and 5-position capacities.

There is no validated simple filter for which it would be responsible to report an executable bankroll, capacity utilization, or deployable maximum-drawdown claim. The independent-trade filter scorecard above is deliberately separated from Phase 2's capacity-constrained wallet accounting.

## Answers

**A. Does the existing MEMESCOPE score predict future token performance?** Only weakly for 1.5×; it is not a robust or monotonic after-cost ranking and does not validate as an execution selector.

**B. Which detection-time features have the strongest genuine predictive relationship?** None is strong. The largest descriptive signals are lower volume/MCAP, lower liquidity/MCAP, lower turnover, and a small positive score association, all with |d| ≤ 0.19. Logistic OOS performance says these do not combine into useful separation.

**C. Why are current high-score signals failing?** The score heavily rewards momentum/reason-code evidence that is common in failures, while the cohort lacks historical ownership, creator, curve, migration, risk, veto, and rank data. High-score failures also show much lower detected liquidity/MCAP than low-score major winners, but that needs forward confirmation.

**D. Can a simple improved filtering rule survive untouched OOS testing?** No. The training-selected low-MCAP/high-buy-pressure rule worsened sharply OOS. The small OOS-positive score-median result was not selected in training and is not evidence.

**E. Is there evidence that rebuilding/reweighting the score could create a tradable edge?** Not yet. There is enough weak structure to justify data-collection and pre-registered research, but not enough to justify reweighting production or automation.

**F. What data should MEMESCOPE collect now?**
- Immutable decision-time score components, risk score, veto/rejection reasons, rank, and full feature availability.
- Holder count, unique buyers/sellers, holder concentration/top-10 ownership, creator/deployer and related-wallet ownership.
- Curve progress, migration state, pool/venue state, and historical liquidity composition.
- Short-window flow and acceleration features captured at the exact decision observation, not a potentially stale nearest snapshot.
- Actual quote, fill, priority fee, slippage, route, and failure data for every paper/devnet attempt.
- Forward outcome labels at fixed horizons and a pre-registered holdout protocol.

## Recommendation

Keep real-money execution disabled and do not alter the live MEMESCOPE score from this Phase 3 cohort. The next useful milestone is a forward-only dataset with the missing decision-time features, frozen candidate rules, and multiple chronological OOS windows—not another retrospective TP/SL or score-weight search.

# V6 FAST-ACCUMULATION — RUN 001 RESULT

`RESEARCH_ONLY`

**Final decision: `NO RELIABLE EDGE IDENTIFIED`**

| | |
|---|---|
| Experiment ID | `V6_FAST_ACCUM_2026_09_13_001` |
| Config hash | `989fe48114ea62dc` (pre-registered, frozen) |
| Dataset version | `803313f86ee19b0f` |
| Spec | `v6-fast-accum-1.0.0` · seed `20260912` |
| Prod release | `89f8330` · live at `https://memescope.site/v6-fast-accum` |
| Leakage audit | **PASSED**, 0 findings |

---

## 1. Dataset

Window `2026-09-11 12:43:43Z → 2026-09-13 08:57:21Z` — **44.23 hours**, 42,621 tokens.

| exclusion | tokens |
|---|---|
| `pruned_series_deleted` (24h pruner) | **20,530** |
| `no_curve_samples` | 826 |
| **usable** | **21,265** |

Data quality is clean: 0 duplicate mints, 0 out-of-order samples, 0 impossible
progress, 0 negative reserves, 0 impossible prices.

Nearly half the archive — 20,530 tokens — has no curve series at all, because the
graduation lab deletes the series of every non-graduate after 24 hours. Those
tokens cannot produce a trade and are excluded with an explicit reason rather
than silently dropped.

---

## 2. Strategy results — IN-SAMPLE ONLY

There is no out-of-sample period (§4). Every number below is measured on the
whole archive, with no train/test separation, and **cannot support a verdict**.

| arm | signals | censored | resolved | win rate | PF | expectancy | net PnL | 2x rate |
|---|---|---|---|---|---|---|---|---|
| FAST-60 | 465 | 206 (44.3%) | 259 | 37.1% | **1.265** | +$0.88 | +$227.70 | 19.8% |
| **FAST-90** | 496 | 203 (40.9%) | 293 | 40.6% | **1.417** | +$1.34 | +$392.40 | 22.8% |
| FAST-120 | 579 | 185 (32.0%) | 394 | 33.8% | **1.053** | +$0.19 | +$73.80 | 21.6% |

Exit mix, FAST-90: 113 take-profit · 145 stop-loss · 18 graduation · 17 time-stop
· 203 censored.

## 3. Controls

| arm | signals | censored | PF | expectancy | win rate |
|---|---|---|---|---|---|
| CONTROL-A — random timing in region | 771 | 185 (24.0%) | **0.762** | −$1.06 | 27.1% |
| CONTROL-B — no Telegram | 579 | 185 (32.0%) | 1.053 | +$0.19 | 33.8% |
| CONTROL-C — no mcap floor | 833 | 182 (21.8%) | **0.837** | −$0.70 | 29.3% |
| CONTROL-D — curve threshold alone | 833 | 182 (21.8%) | **0.837** | −$0.70 | 29.3% |

**The control design partly collapsed, as predicted.** With the Telegram overlay
UNAVAILABLE the base rule already runs without Telegram, so base ≡ CONTROL-B
(FAST-120 and CONTROL-B are the same 579 trades, identical to the last decimal),
and CONTROL-C ≡ CONTROL-D. Three distinct arms exist, not five: curve+mcap,
curve-only, and random-timing.

Read at face value this looks encouraging: FAST-90 at PF 1.417 beats
random-timing (0.762) and curve-only (0.837), and the mcap floor looks
load-bearing — dropping it takes PF from 1.053 to 0.837. **Section 5 is why that
reading is not safe.**

## 4. Walk-forward — the gate

```
weekly (pre-registered):  INSUFFICIENT_HISTORY   0 folds
daily  (exploratory):     INSUFFICIENT_HISTORY   0 folds
OOS trades: 0
```

44 hours cannot form a train/test pair at either width (weekly needs 14 days,
daily needs 48 hours). The fold width was **not** reduced to manufacture a fold;
that would be the tuning §11 forbids.

| # | gate condition | status |
|---|---|---|
| 1 | OOS profit factor ≥ 1.5 | NOT_EVALUABLE |
| 2 | ≥ 100 OOS trades | NOT_EVALUABLE |
| 3 | no token > 20% of OOS profit | NOT_EVALUABLE |
| 4 | every test week profitable | NOT_EVALUABLE |
| 5 | positive after fees and slippage | NOT_EVALUABLE |
| 6 | survives multiple-comparison | NOT_EVALUABLE |
| 7 | bootstrap CI not outlier-driven | NOT_EVALUABLE |

A condition that cannot be evaluated **fails**. "No evidence against" is not
"satisfied".

## 5. Censoring — why the in-sample numbers point up

38.6% of signals are censored (594 censored, 946 resolved). That would be
survivable if censoring were random. **It is not.**

| why polling stopped | % of CENSORED | % of RESOLVED | ratio |
|---|---|---|---|
| `evicted` — watch set full, **lowest progress dropped first** | **38.7%** | 11.5% | **3.4×** |
| `silent` — reserves stopped moving for 30 min | **36.5%** | 27.4% | 1.3× |
| `shutdown` | 21.4% | 34.0% | 0.6× |
| `post_migration` | 0.0% | 22.9% | — |

Eviction is **3.4× over-represented** among censored trades, and eviction
removes the *least-progressed* token. Silence — a token whose reserves stopped
moving — is over-represented too. Both describe a token that is dying. **The
censoring preferentially deletes losers**, which inflates every profit factor
above.

And the bias is **strongest exactly where the result looks best**: the base arms
are censored far more than the controls (FAST-60 44.3%, FAST-90 40.9% versus
CONTROL-A 24.0%, CONTROL-C/D 21.8%). If censoring deletes losers, the base arms
collect more of that benefit than the controls do. That mechanism alone could
produce the entire base-versus-control gap in §3, with no edge present.

This is why FAST-90's apparent significance is not evidence.

## 6. Statistics — Benjamini-Hochberg, α = 0.05

Six hypotheses tested; one-sided t-test on mean net PnL > 0.

| arm | raw p | adjusted p | reject null | Cohen's d |
|---|---|---|---|---|
| **FAST-90** | 0.0043 | **0.0301** | **yes** | 0.153 |
| FAST-60 | 0.0501 | 0.1755 | no | 0.102 |
| FAST-120 / CONTROL-B | 0.3253 | 0.5693 | no | 0.023 |
| CONTROL-C / CONTROL-D | 0.9720 | 0.9940 | no | −0.075 |

FAST-90 survives BH correction. **This does not make it an edge.** The test is
in-sample, on a sample whose censoring is demonstrably tilted toward deleting
losers, with no out-of-sample confirmation. The effect size is small (d = 0.15).
Gate condition 6 remains NOT_EVALUABLE because it is defined on OOS trades,
which do not exist.

## 7. Leakage audit

**PASSED** — 0 findings across all arms, after a fix the audit itself forced.

The first run **aborted**. A completed pump.fun curve zeroes all four reserves,
so the graduation sample carries no price; `simulate()` exited "at" it, fell into
the unpriced branch, and returned a **censored** trade still labelled
`exit_reason=graduation`. The audit rejects that pair and refused to report a
number. Without it, every graduating token would have been silently booked as
unresolved and the run would have printed a clean, wrong result. The position now
exits at the last priced print before migration — which is also what a seller
actually gets.

Audit scope is narrow by design: feature timestamps, exit ordering, graduation
carry. It cannot see retention or sampling bias, which act before a feature
exists — those are measured in §5.

## 8. Execution model

$10 fixed · 5 concurrent · $50 max deployed · one position per mint. Entry and
exit filled against the curve's own reserves via the graduation lab's
`curve_fill_buy`/`curve_fill_sell`, which model pump.fun's fee asymmetry exactly
(1.25% as a markup on the way in, a deduction on the way out) and deepen the
curve as the position fills. Plus 25 bps adverse slippage per leg and 0.002 SOL
priority fee on both. SOL/USD frozen at 150 and recorded in the config hash;
every ratio metric is invariant to it.

## 9. Final decision

**`NO RELIABLE EDGE IDENTIFIED`**

Stopped at the data layer, not the edge layer. The hypothesis is **neither
supported nor refuted** — 44 hours of archive cannot test it. The one directional
hint (FAST-90 beating every control, surviving BH) is exactly what §5's censoring
bias would manufacture, and the base arms carry the most censoring.

**What would settle it:** roughly five to six weeks of forward collection, plus
three collector changes that remove the bias rather than measure it —
retain the first ~35 minutes of every token, hold an entered token for its full
30-minute horizon regardless of silence or room, and persist the launch `uri` so
the Telegram leg becomes testable. Until the second of those exists, a longer
archive would still be censored toward winners.

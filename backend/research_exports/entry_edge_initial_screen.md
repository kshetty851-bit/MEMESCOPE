# Entry Edge Research — Bounded Initial Screen

> Research only; immutable snapshots read, no wallet rows written.

## Historically available at the reconstructed entry snapshot

- price, liquidity, market cap, volume 5m/1h/24h, buy/sell 24h counts, DEX/pair/pool, provider latency, trading status and verification.
- Candidate ledger also contains entry rank. Historical Radar component/evidence, holders, concentration, token age, confidence/risk and 6h fields were not joined into this first audit because no immutable entry-timestamp record was established for all opportunities.
- Market cap is explicitly excluded from gates pending independent quality validation.

## Fixed-gate replay results

| Gate | opportunities | return | PF | expectancy |
|---|---:|---:|---:|
| baseline survival >= 1.25 | 136 | -44.33% | 0.61 | $-9.36 |
| liquidity >= $5k | 113 | -36.07% | 0.72 | $-6.79 |
| liquidity >= $10k | 101 | -30.56% | 0.72 | $-6.62 |
| turnover >= 2.0 | 56 | -50.01% | 0.61 | $-9.60 |
| turnover >= 5.0 | 43 | -48.00% | 0.53 | $-11.98 |
| liquidity >= $5k AND turnover >= 2.0 | 46 | -21.07% | 0.79 | $-4.66 |

## Chronological holdouts

The same frozen gates were evaluated on early-60/late-40 and early-70/late-30 opportunity cohorts. No gate was selected from full-history performance.

| Gate | 60/40 late return / PF / expectancy | 70/30 late return / PF / expectancy |
|---|---:|---:|
| baseline survival >= 1.25 | -57.12% / 0.38 / $-19.97 | -33.05% / 0.50 / $-13.86 |
| liquidity >= $5k | -45.53% / 0.42 / $-18.97 | -21.54% / 0.55 / $-12.67 |
| liquidity >= $10k | -42.88% / 0.26 / $-26.80 | -24.41% / 0.26 / $-24.41 |
| turnover >= 2.0 | -50.94% / 0.39 / $-19.59 | -37.07% / 0.41 / $-18.54 |
| turnover >= 5.0 | -46.75% / 0.26 / $-23.38 | -32.54% / 0.29 / $-20.34 |
| liquidity >= $5k AND turnover >= 2.0 | -37.54% / 0.42 / $-18.77 | -26.94% / 0.44 / $-17.96 |

## Finding

No gate is considered validated unless its later cohort has positive expectancy and PF > 1. This bounded screen is deliberately not a parameter search.

## Limitations

- This report does not claim Radar inversion causes: immutable historical Radar component rows were not established for every entry timestamp.
- The canonical historical Jupiter-quote limitation remains: the production legacy fallback cost model is used, not fabricated historical Jupiter quotes.

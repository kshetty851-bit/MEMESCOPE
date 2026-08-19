# Scanner 2× Quality Audit — Initial Reproduction

## Exact reproducible baseline

This read-only baseline uses every mint with an immutable positive-price market
snapshot. The reference is its first positive observed snapshot; the outcome is
the maximum later observed positive price. It has no fixed forward horizon, so
it is an all-available-history ceiling, not a 24-hour hit rate. Tokens with no
later observation are included and therefore explicitly make this a discovery
population measurement rather than a claim about fully covered candidates.

| Population | n | 1.25× | 1.5× | 2× | 3× | 5× | 10× |
|---|---:|---:|---:|---:|---:|---:|---:|
| All first-positive snapshot mints | 125,852 | 4,890 (3.89%) | 3,623 (2.88%) | 2,360 (1.88%) | 1,377 (1.09%) | 768 (0.61%) | 372 (0.30%) |

## Finding

The claimed approximately 28% two-times statistic is **not reproduced** under
the broad, immutable scanner-discovery definition above. It must refer to a
narrower population or a different reference price/horizon. It must not be
used as a scanner-quality claim until that cohort is identified reproducibly.

## Reproduced scanner-selected cohort

The source of the earlier figure is now identified precisely: `radar_tokens`,
using its immutable `first_price` at first Radar detection and immutable
`peak_multiple` thereafter.

| Population | Reference | n | 2× | 3× | 5× | 10× |
|---|---|---:|---:|---:|---:|---:|
| Raw discovered snapshot mints | first positive snapshot | 125,852 | 2,360 (1.88%) | 1.09% | 0.61% | 0.30% |
| Radar detected tokens | `radar_tokens.first_price` | 391 | 111 (28.39%) | 65 (16.62%) | 32 (8.18%) | 15 (3.84%) |

Radar admission therefore enriches the observed 2× rate by **15.1×** versus
the raw first-positive-snapshot population (28.39% / 1.88%). This is evidence
that discovery plus Radar admission is materially selective; it is not yet
evidence that rank ordering within the Radar is calibrated.

## Selection-time winner comparison

`radar_tokens.first_*` is immutable first-selection state. It supports this
comparison without reconstructing current values:

| Cohort | n | median liquidity | median 24h volume | mean score | mean confidence |
|---|---:|---:|---:|---:|---:|
| Future 2× | 111 | $14,794 | $85,898 | 62.61 | 62.11 |
| Did not reach 2× | 280 | $18,947 | $68,044 | 63.49 | 59.56 |

At first selection, winners had higher median 24-hour volume and confidence,
but slightly lower liquidity and score. This is not a monotonic score signal;
it is descriptive only and does not justify a production threshold.

## Time to 2× after first Radar selection

All 111 immutable 2× achievements were measured from `first_detected_at`:

| Statistic | Minutes |
|---|---:|
| p25 | 15.0 |
| Median | 109.4 |
| p75 | 714.3 |
| p90 | 1,420.5 |

27 reached 2× within 15 minutes, 44 within one hour, and 100 within 24 hours.
Radar found a large part of the winning cohort early enough for meaningful
remaining upside, but a quarter doubled within about fifteen minutes.

## Not historically provable in this dataset

Exact rank-at-selection, top-N cohorts, selection-time 5m/1h fields,
transaction windows, and per-selection Radar component/risk payloads are not
frozen for all 391 historic selections. Ranking calibration and quality-filter
OOS validation would require reconstructing mutable state and are therefore
excluded. The forward decision ledger is the correct remedy.

## Trustworthy architecture facts

Scanner discovery and Radar ranking are separate. Radar weights currently are
Momentum 28%, Technical 22%, Liquidity Quality 18%, Community 15%, On-chain
Health 12%, Risk 5%.

## Limits preventing the requested calibration audit today

The current historical schema does not preserve an immutable, decision-time
scanner eligibility/ranking cohort for every detection, nor a complete historic
Radar component payload per rank event. Consequently it cannot honestly produce
Top-20/10/5/3 calibration, score buckets, rank monotonicity, component
inversion, or causal discovery-to-Radar-stage latency without reconstructing
mutable/current state. That would violate this audit's no-look-ahead rule.

## Conclusion

No validated scanner improvement is proposed. The minimum forward ledger work
already authorized is required before a complete scanner-ranking calibration can
be performed honestly.

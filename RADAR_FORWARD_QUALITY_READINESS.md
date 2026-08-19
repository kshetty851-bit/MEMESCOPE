# Radar forward-quality dataset readiness

Status: live as of 2026-08-15. This is instrumentation only. It does not add a
quality filter, alter Radar scoring/ranking, or change Scanner, wallet, or
execution behaviour.

## 1. Existing architecture verified

The implementation was based on the current Radar scorer, detector, repository,
service/sweep, market-enrichment worker, market-snapshot model, Celery schedule,
existing tests, and `SCANNER_2X_QUALITY_AUDIT.md`. The audit's stated baseline
is retained: historical 2X rate for Radar-selected tokens is 28.39%; this work
does not reinterpret or backfill that history.

## 2. Schema and migrations added

Migration `0028_radar_forward_quality` adds only these append-only tables:

- `radar_decision_snapshots`
- `radar_rank_events`
- `radar_decision_outcomes`

It was applied successfully. `alembic current` reports
`0028_radar_forward_quality (head)`.

## 3. Exact Radar fields frozen

Each decision row freezes its deterministic evaluation identity, mint/token
identity, decision time, discovery age, canonical market-snapshot link, score,
confidence, risk/risk band, eligibility, selected state, selection/rejection
reasons, vetoes, evidence, why-now signals, and Radar algorithm/configuration
and feature-schema versions. Ranking is recorded from the committed canonical
board immediately after the Radar transaction; the distinct `rank_observed_at`
field makes that observation point explicit.

## 4. Component data captured

The JSON component payload freezes Momentum, Technical, Liquidity Quality,
Community, On-chain Health, and Risk exactly as evaluated: raw inputs,
normalised score, declared and effective weights, weighted contribution,
evidence, vetoes, and availability state.

## 5. Market data captured

The immutable market payload captures available price, liquidity, 5m/1h/24h
volume, 24h buy/sell counts and transaction count, DEX, pool, pair, provider,
provider latency, market status, verification status, and observation time.
Every record points to the exact source `market_snapshot_id` when one exists.

## 6. Derived pre-decision features

Frozen features include available volume-to-liquidity and buy/sell ratios,
snapshot count since discovery, median observation cadence, time since the
previous valid observation, and support-dependent volume/transaction/liquidity
and price velocity/acceleration. The calculation filters observations to
`captured_at <= evaluated_at`; a dedicated test injects an extreme future point
and proves it is excluded.

## 7. Rank-history architecture

`radar_rank_events` is append-only. It stores every captured evaluation rank
plus Top-20 board changes, preserving first Radar appearance and later
Top-20/10/5/3/1 progression instead of updating a mutable rank field.

## 8. Control-population capture policy

All selected Radar evaluations are recorded. Non-selected evaluations record
when near admission (within five score points of `MIN_RADAR_SCORE`) or when
included by a stable SHA-256 mint-hash 1/N control sample (`N=20` by default).
The policy is frozen in each record's provenance. This provides selected and
near-miss controls without recording every low-signal refresh.

## 9. Outcome architecture

`radar_decision_outcomes` is a separate append-only labels table with a unique
`(decision_id, outcome_kind, horizon)` key. It never updates a decision-time
snapshot and is not read by Radar scoring/ranking.

## 10. Outcome horizons

The label worker runs every five minutes and records the first canonical market
observation at or after 5m, 15m, 30m, 1h, 3h, 6h, 12h, and 24h when coverage
exists. At 24h it also records an independent path summary.

## 11. 2X/3X/5X/10X tracking capability

Outcome rows retain the decision reference price, observation price, future
multiple, and market state. The 24-hour path summary supports maximum future
multiple, MFE, MAE, time-to-1.25X/1.5X/2X/3X/5X/10X, time to peak, liquidity
survival/collapse, and market-disappearance evidence. These are labels only.

## 12. Availability and provenance model

Important absent fields are never represented as an unexplained null.
`availability` distinguishes `AVAILABLE`, `NOT_AVAILABLE_FROM_PROVIDER`,
`NOT_YET_ENRICHED`, and `NOT_APPLICABLE`, with source/provider/observation-time
metadata where applicable. `provenance` also records the snapshot link, rank
observation semantics, and capture policy.

## 13. Feature schema and versioning

Forward rows use `radar_quality_feature_v1` and configuration version
`radar_weights_v1`, alongside the Radar result's algorithm/model version. This
keeps future model or schema revisions interpretable without rewriting history.

## 14. Idempotency design

`evaluation_id` is UUID5 over feature-schema version, mint, evaluation time,
and exact market-snapshot ID. The matching evaluation key and rank-event keys
are unique. A technical retry is therefore a no-op; a later evaluation remains
a distinct observation.

## 15. Failure isolation

Radar's canonical transaction commits before the recorder opens its independent
transaction. The recorder and a second service boundary catch/log persistence
errors rather than propagating them into Radar, ranking, Scanner, or selection.
The failure-injection test proves that score, confidence, category, active
state, and canonical ranking are identical before and after a recorder failure.

## 16. Performance impact

Capture is post-commit, bounded by the control policy, and does no optional
provider enrichment. In live traffic, real batches of 1--16 decision candidates
took 9.547--163.164 ms for their separate ledger transaction. The first
100-decision 5m outcome pass took 0.222 s. These are operational measurements,
not a synthetic throughput claim; no Scanner path was changed and no ranking
write waits on a successful ledger write.

## 17. Live pipeline verification

The normal enrichment/Radar pipeline created real records without manufacturing
an opportunity. At the verification point it contained:

| Ledger | Count |
| --- | ---: |
| Decision snapshots | 1,825 |
| Rank events | 2,020 |
| Outcome labels | 100 |

The registered `radar_quality_outcomes` Celery task examined 100 mature
decisions and wrote 100 real 5m labels. The 24h summary had not yet become due,
which is expected for a newly-live forward dataset.

## 18. Tests

- `tests/integration/test_radar_quality.py`: 5 passed (frozen values,
  availability, no-lookahead features, append-only/idempotent ranks, separate
  outcomes, and injected persistence failure).
- Existing Radar pipeline/platform/engine/purity/readout suites passed in the
  focused regression run.
- `tests/integration/test_scanner.py`: 7 passed in 93.54 seconds.
- Ruff check/format check passed for task-scoped source and tests.
- Mypy passed for `app/radar/quality.py` and `app/models/radar_quality.py`.

`alembic check` still reports only pre-existing default drift in the unrelated
paper-research/report-delivery models. It reports no `radar_*` drift.

## 19. Files changed

- `backend/alembic/versions/20260815_0028_radar_forward_quality.py`
- `backend/app/models/radar_quality.py`
- `backend/app/models/__init__.py`
- `backend/app/radar/quality.py`
- `backend/app/radar/models.py`
- `backend/app/radar/repository.py`
- `backend/app/radar/service.py`
- `backend/app/radar/scheduler.py`
- `backend/app/services/market/worker.py`
- `backend/app/workers/celery_app.py`
- `backend/app/core/config.py`, `.env.example`, `docker-compose.yml`
- `backend/tests/integration/test_radar_quality.py`
- `backend/tests/unit/test_radar_purity.py`

## 20. Fields still unavailable from providers

The present market schema does not supply 6h volume; price-change windows;
5m/1h/6h buy/sell counts; short-window transaction counts; or quote-age/freshness.
They are stored as explicitly unavailable rather than inferred. Community also
remains unavailable when Radar reports it unavailable. No current-state data is
used to manufacture historical availability.

## 21. Sanitized real Radar snapshot example

One newly-created live row (mint intentionally omitted) froze:

| Field | Value |
| --- | --- |
| Evaluated | 2026-08-15T17:34:36.060636Z |
| Rank / state | #2 / `RANKED` |
| Radar / confidence / risk | 70.141 / 85.000 / 78.898 |
| Selected | true |
| Exact market snapshot linked | true |
| Feature schema / algorithm | `radar_quality_feature_v1` / `radar-v1` |
| Momentum component frozen | true |
| 5m-volume/liquidity feature | `AVAILABLE` |
| 6h-volume field | `NOT_AVAILABLE_FROM_PROVIDER` |

## 22. Radar output before versus after

Confirmed identical for the failure-isolation path: the test snapshots the
canonical Radar score, confidence, category, active state, and ranking, injects
a ledger failure, and asserts every value is unchanged. The live writer only
observes the committed Radar result in a new transaction.

## 23. Scanner behaviour

Confirmed unchanged. No Scanner discovery, eligibility, parser, or queue code
was modified. The complete existing Scanner integration suite passed 7/7.

## 24. No strategy, ranking, or filter activated

Confirmed. No Radar weights, score formula, detector threshold, ranking order,
confidence/risk calculation, Scanner eligibility rule, paper-wallet strategy,
or execution path was changed. There is no historical backfill, V1.2 strategy,
quality filter, or ML model in this implementation.

# MEMESCOPE mappings that must be connected

The attachments name candidate repository paths and tables, but do not provide the exact live schema. `config/memescope_mapping.yaml` therefore ships with `status: unresolved`; the adapter refuses to run until it is changed to `connected`.

## Candidate locations to verify

- `app/labs/graduation/models.py`: `grad_tokens`, `grad_migrations`, `grad_postgrad_samples`, `grad_early_opens`, `grad_paper_positions`, `grad_trades`.
- `app/models/graduation.py`: `pumpfun_graduations`, `pumpfun_graduation_marks`.
- `app/models/real_wallet_execution.py`: `real_wallet_positions`, live intents, execution events, balance observations, autotrade events, kill-switch history.
- `app/real_wallet/live_repository.py` and reconciliation code.
- `app/labs/graduation/backtest.py`, `paper.py`, `held_watch.py`, and `config.py` for exact rule/version semantics.

## Required mapping decisions

1. Use full mint and pool addresses as joins. Never use symbol plus minute as identity.
2. Map both event timestamp and ingestion/availability timestamp. Every feature uses the latter for leakage checks.
3. Export the full eligible opportunity universe, including rejected, unbought, failed, delisted, and unresolved opportunities; a bought-only set is selection-biased.
4. Define quiet-pool count as actual lifetime swaps since verified graduation/opening, not a rolling count.
5. Distinguish native quote reserves from USD liquidity changes caused by SOL/USD.
6. Exclude verified AMM/custody accounts from holder concentration only when the classification was known at decision time.
7. Creator/funder cluster links need evidence timestamp, source, confidence, and a prior independently confirmed malicious event. Do not infer fraud from a price loss alone.
8. For outcomes/backtests, export size-specific all-in entry cost and exit proceeds including every fee and failed attempt. Do not linearly resize recorded P&L.
9. Preserve strategy versions and historical rule-change timestamps.
10. Mark unknown or uncollected values as missing, not zero.

## Connection acceptance checklist

- All `TODO` values are gone.
- `status: connected` is set only after a schema review.
- A fixture from the real export passes `validate`.
- Spot checks prove every `observed_at <= decision_ts`.
- Train/validation/test periods are chronological and the final test was not used to set thresholds.
- The October 1-12, 2026 research interval is labelled development data, not pristine out-of-sample evidence.

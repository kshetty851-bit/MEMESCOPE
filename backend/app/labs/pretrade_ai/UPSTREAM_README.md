# MEMESCOPE pre-trade AI scoring package

A complete, offline package for ranking **trade candidates before entry**. It does not replace the existing exit logic, execute transactions, sign anything, deploy code, alter a database, or update production automatically.

## Why this package is entry-first

The supplied research supports selection as the next priority:

- In the earlier 901-trade, $50 historical ledger, the $50K-$75K band contained 159 trades and +$446.33 recorded net P&L; the ten largest winners entered at $50,975-$57,478. Those are retrospective, fixed-ledger findings, not a causal or forward-performance claim.
- In the later 902-trade, $10 cash-limited Astra replay, the original strategy produced +$97.81; only $50K-$75K produced +$91.75 on 159 trades; only $50K-$100K produced +$98.60 with lower reported drawdown; skipping $150K-$200K produced +$117.32 but slightly higher drawdown. The report covers October 1-12, 2026 and explicitly warns that the period has already been inspected.
- The corrected Astra run found look-ahead in back-dated DEX Screener observations. After using knowledge time rather than quoted event time, a -10% stop no longer improved the baseline. This package therefore validates every feature's `observed_at` against `decision_ts`.
- Broad holder/buyer/name filters removed many winners in the supplied replay. Creator/funder identity is retained as a risk score only when the linkage was knowable before entry; missing identity is not treated as safe.

These findings motivate the architecture; none is embedded as a synthetic performance promise.

## Package contents

- Point-in-time JSONL schema with per-feature observation timestamps.
- Leakage-safe chronological train/validation/test split with label embargo and mint/creator/funder group purge.
- Deterministic logistic model with median imputation, missingness indicators, scaling, and class balancing.
- Configurable `ACCEPT`, `REVIEW`, `REJECT`, and `INSUFFICIENT_DATA` thresholds.
- Liquidity prior that prioritizes $50K-$75K research and flags the historically weak $150K-$200K band.
- Creator/funder risk score based on dated prior confirmed-rug links, confidence, pre-entry creator selling, and reserve deterioration.
- Offline selection-only portfolio replay against `baseline_eligible` opportunities using identical supplied entry/exit outcomes.
- Local advisory outbox only; every record explicitly disallows execution and production writes.
- Blocked MEMESCOPE mapping template listing every live-schema connection still required.

## Install

```bash
cd MEMESCOPE-pretrade-ai
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e .
pytest
```

No credential is included or required for examples/tests.

## Exact smoke/demo commands

The generator creates deterministic **synthetic software fixtures only**. Its metrics test plumbing and must not be reported as strategy performance.

```bash
mkdir -p artifacts
python examples/generate_demo_data.py --output artifacts/demo_history.jsonl
python -m memescope_pretrade_ai.cli validate --input artifacts/demo_history.jsonl
python -m memescope_pretrade_ai.cli train \
  --input artifacts/demo_history.jsonl \
  --config config/default.yaml \
  --output-dir artifacts/model
python -m memescope_pretrade_ai.cli score \
  --input examples/score_input.jsonl \
  --config config/default.yaml \
  --model artifacts/model/model.joblib \
  --output artifacts/scores.jsonl \
  --acknowledge-no-execution
python -m memescope_pretrade_ai.cli backtest \
  --input artifacts/demo_history.jsonl \
  --config config/default.yaml \
  --model artifacts/model/model.joblib \
  --output artifacts/backtest.json
```

Equivalent one-command smoke run:

```bash
bash scripts/run_demo.sh
```

## Connect real MEMESCOPE data safely

1. Read `MAPPING_REQUIRED.md`.
2. Inspect the current repository and live read-only schema. The candidate paths/tables are in `config/memescope_mapping.yaml`.
3. Create a database role that is technically read-only. Do not use wallet/trading credentials.
4. Build a complete point-in-time export with the provided canonical shape. Use `sql/read_only_export_template.sql` only after replacing and reviewing every `TODO`.
5. Resolve every mapping path, document its timestamp semantics, and change mapping `status` from `unresolved` to `connected`.
6. Convert a raw read-only JSONL export:

```bash
python -m memescope_pretrade_ai.cli map-records \
  --input /read-only/export/raw_opportunities.jsonl \
  --mapping config/memescope_mapping.yaml \
  --output artifacts/memescope_opportunities.jsonl
python -m memescope_pretrade_ai.cli validate \
  --input artifacts/memescope_opportunities.jsonl
```

The adapter deliberately refuses unresolved mappings.

## Train without leakage

```bash
python -m memescope_pretrade_ai.cli train \
  --input artifacts/memescope_history_with_outcomes.jsonl \
  --config config/default.yaml \
  --output-dir artifacts/candidate-YYYYMMDD
cat artifacts/candidate-YYYYMMDD/training_report.json
```

Rules enforced:

- Sort by `decision_ts`; never random-split.
- A training label must be available before the next block, minus the embargo.
- Embargo defaults to 15 minutes, exceeding the ten-minute candidate horizon plus settlement overlap; increase it if live settlement is slower.
- Reused mints and creator/funder clusters are purged across later blocks.
- The supplied October 1-12 data is development data. A split within it is a robustness check, not untouched validation.
- Thresholds are read from configuration and are not optimized on test results.
- Unknown features remain missing; the model uses missingness indicators. Missing does not become zero or safe.

Before prospective use, freeze the config/model hash and evaluate on a later, previously uninspected period. If none exists, report `forward validation pending`.

## Score in shadow mode

With a trained model:

```bash
python -m memescope_pretrade_ai.cli score \
  --input artifacts/current_point_in_time_snapshots.jsonl \
  --config config/default.yaml \
  --model artifacts/candidate-YYYYMMDD/model.joblib \
  --output artifacts/shadow/scores-$(date -u +%Y%m%dT%H%M%SZ).jsonl \
  --acknowledge-no-execution
```

Without `--model`, scoring runs a transparent rules-only fallback and says so in each record. Use that only for integration testing, not as a trained AI claim.

The outbox is owner-readable/writable only, is written atomically, and contains:

```json
{"decision":"ACCEPT","execution_authorized":false,"production_write_authorized":false,"integration_contract":{"mode":"advisory_only","may_execute_trade":false,"may_modify_production":false,"consumer_must_revalidate_at_use_time":true}}
```

`ACCEPT` means “passes the research threshold,” never “place an order.” Keep the consumer disconnected from signing and order-submission paths during shadow evaluation.

## Offline comparison against the existing strategy

The input outcome must contain size-specific `matched_size_entry_cost_usd` and `matched_size_exit_proceeds_usd`, with all costs included. The package refuses mismatched stake sizes rather than linearly scaling P&L.

```bash
python -m memescope_pretrade_ai.cli backtest \
  --input artifacts/memescope_history_with_matched_size_outcomes.jsonl \
  --config config/default.yaml \
  --model artifacts/candidate-YYYYMMDD/model.joblib \
  --output artifacts/candidate-YYYYMMDD/backtest.json
```

The comparison is intentionally selection-only:

- Control: every `baseline_eligible=true` opportunity.
- AI gate: the same opportunities, entries, exits, stake, and costs, restricted to configured accepted decisions.
- Both are replayed chronologically with cash, concurrency, and exposure limits.
- Report includes skipped winners, skipped losers, forgone P&L, capacity blocks, untestable outcomes, paired net-P&L difference, and realized drawdown.

This does not reconstruct absent historical quotes, routes, creator trades, or sellability. Rows lacking resolved all-cost matched-size outcomes are `untestable`.

## Configuration and threshold policy

Edit a copy of `config/default.yaml`; retain the frozen original with each model. Defaults are research hypotheses, not production optima.

- `accept_score`: automatic shadow accept threshold.
- `review_score`: below accept but suitable for manual analysis.
- `hard_reject_risk`: creator/funder risk ceiling.
- `minimum_feature_completeness`: otherwise `INSUFFICIENT_DATA`.
- Hard gates cover liquidity, quiet-pool count, quote freshness, price impact, round-trip cost, and authority checks when observed.
- Liquidity prior favors $50K-$75K and downweights $150K-$200K, while the trained model can use all point-in-time features.

Change thresholds only using training/validation evidence, freeze them, and evaluate once on untouched later data. Never tune against the final test.

## Creator/funder risk interpretation

The score uses only point-in-time evidence:

- Dated prior **confirmed** malicious links for creator and funder clusters.
- Identity confidence.
- Recency of the prior link.
- Creator-cluster selling before entry.
- Native quote-reserve deterioration before entry.

A price collapse does not itself create a confirmed-rug label. A repeated token name is never identity evidence. Future cluster discoveries cannot be backfilled as if known earlier.

## Input schema

See `schemas/opportunity.schema.json` and `examples/score_input.jsonl`. Each feature is wrapped as:

```json
{"value":56000,"observed_at":"2026-10-13T04:01:00Z","source":"collector_name","quality":"observed"}
```

`observed_at` is the time MEMESCOPE could use the value, not merely the chain event time. Validation fails if it is later than `decision_ts`.

Training/backtest rows add:

```json
{"outcome":{"label_available_ts":"2026-10-13T04:07:00Z","exit_ts":"2026-10-13T04:06:00Z","matched_size_entry_cost_usd":10,"matched_size_exit_proceeds_usd":10.42,"all_costs_included":true,"unresolved":false,"source":"read_only_reconciliation"}}
```

## Tests

```bash
pytest
```

Coverage includes future-observation rejection, chronological label embargo, group purge, creator/funder risk, configurable thresholds, safe outbox flags/permissions, and deterministic portfolio accounting.

## Production boundary

This archive is ready for local research and shadow integration. It is intentionally **not** production-connected. Production connection requires: exact schema mappings, read-only point-in-time export validation, a frozen model/config, untouched forward evidence, security review, and a separate human change-management process. This package must never be granted wallet signing or order-submission capability.

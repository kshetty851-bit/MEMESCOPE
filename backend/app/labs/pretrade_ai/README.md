# Pre-trade AI lab

An isolated scoring and **paper-trading lab**, imported from `MEMESCOPE-pretrade-ai-2.zip`. It scores candidate entries and compares selection decisions using supplied historical outcomes. It does not change any existing entry/exit strategy or wallet.

The offline commands remain isolated. The separately launched `memescope_pretrade_ai.service` now reads three market tables through a SELECT-only database role and writes only its own SQLite paper ledger. It has no exchange client, signer, wallet hook or import into platform workers. The paper service runs continuously without the browser open.

## Website interface

The website route is `/pretrade-ai`, linked as **Pre-trade AI Lab** in navigation. It reviews locally opened advisory `scores.jsonl` exports: filter decisions, search candidates, and inspect score explanations. Files remain in the browser and are not uploaded or saved. A labeled synthetic sample demonstrates the interface. The same page also displays the live scanner, paper account, positions, fills and assessments through an alpha-authenticated read-only status endpoint. Training remains offline. Imported files cannot trigger paper trades.

## Quick start

From the repository root, the environment has already been installed locally. Run:

```bash
cd backend
app/labs/pretrade_ai/.venv/bin/python -m app.labs.pretrade_ai status
app/labs/pretrade_ai/.venv/bin/python -m app.labs.pretrade_ai demo
```

The demo generates 120 deterministic **synthetic software fixtures**, trains the model, and scores/backtests only the chronological held-out test rows. Outputs appear under `artifacts/demo/`:

- `summary.json`: smoke-test status, explicitly marked as non-performance evidence.
- `history.jsonl` and `holdout.jsonl`: synthetic input and test partition.
- `model.joblib` and `training_report.json`: model and split diagnostics.
- `scores.jsonl`: advisory decisions with execution and production-write authorization set to false.
- `backtest.json`: offline control-versus-selection comparison.

These results verify software plumbing. They are not real-market returns or proof of a profitable strategy. The imported defaults remain research hypotheses, including the $300 simulated cash balance and $10 matched-size entries; they do not alter an existing wallet or implement the earlier Bitcoin monthly-reset experiment.

## Fresh installation

From the repository root, use a separate environment:

```bash
python3.12 -m venv backend/app/labs/pretrade_ai/.venv
backend/app/labs/pretrade_ai/.venv/bin/python -m pip install -e 'backend/app/labs/pretrade_ai[dev]'
```

Python 3.11 or 3.12 is recommended for the imported dependency versions. Do not install these dependencies into the main backend environment. Dependencies in the supplied package are pinned; `requirements-resolved.txt` records the versions used for this local verification.

## Commands for exported data

Run these from `backend/`. Inputs can be existing local exports. Output and model paths must resolve inside this lab's `artifacts/` directory; traversal and symlink escapes are rejected. When omitted, `--config` uses this lab's `config/default.yaml`.

```bash
# Validate canonical records without accessing a database.
app/labs/pretrade_ai/.venv/bin/python -m app.labs.pretrade_ai validate \
  --input /absolute/path/to/opportunities.jsonl

# Train on historical records with resolved, all-cost, size-matched outcomes.
app/labs/pretrade_ai/.venv/bin/python -m app.labs.pretrade_ai train \
  --input /absolute/path/to/history.jsonl \
  --output-dir app/labs/pretrade_ai/artifacts/candidate

# Write advisory scores; ACCEPT never places a trade.
app/labs/pretrade_ai/.venv/bin/python -m app.labs.pretrade_ai score \
  --input /absolute/path/to/candidates.jsonl \
  --model app/labs/pretrade_ai/artifacts/candidate/model.joblib \
  --output app/labs/pretrade_ai/artifacts/candidate/scores.jsonl \
  --acknowledge-no-execution

# Compare selection against the same supplied entries/exits on later rows.
app/labs/pretrade_ai/.venv/bin/python -m app.labs.pretrade_ai backtest \
  --input /absolute/path/to/later_holdout.jsonl \
  --model app/labs/pretrade_ai/artifacts/candidate/model.joblib \
  --output app/labs/pretrade_ai/artifacts/candidate/backtest.json
```

Scoring without `--model` is supported and explicitly labeled `rules-only-v1`. Only load locally trained, trusted model files: joblib serialization can execute code. Keep model/config pairs frozen for evaluation. The training-overlap guard prevents replay on training rows, but cannot know whether an analyst has already inspected a later period or tuned thresholds on it; untouched forward validation remains pending.

`map-records` converts already exported JSONL files. The supplied mapping is deliberately unresolved and cannot run until its fields and timestamp provenance are verified. Merely changing its status does not bypass unresolved `TODO` checks. Missing or string-valued baseline eligibility is rejected rather than silently coerced. Optional `outcome` mappings preserve supplied matched-size outcomes.

The live adapter reads `grad_migrations`, `grad_tokens` and `grad_postgrad_samples`. No real market model has been trained. The feed does not supply the required authority checks, sell route, lifetime swap count or enough complete features: these remain missing and block entries. Rules are not relaxed to force trades. Do not treat the supplied archive's historical research claims as independently verified findings. Existing wallet configuration is not used. The service receives only a dedicated SELECT-only database credential and validates browser sessions through the existing alpha endpoint.

## Validation

From the repository root:

```bash
backend/app/labs/pretrade_ai/.venv/bin/python -m pytest backend/app/labs/pretrade_ai/tests
```

Local result: **17 tests passed**, plus a complete synthetic demo. Tests cover the supplied scoring/splitting/accounting behavior and added isolation, output containment, unresolved mapping, strict eligibility, outcome mapping, duplicate records, nonfinite outcomes, dated identity evidence, and training-overlap rejection.

## Import provenance and local fixes

All 37 files in the supplied manifest were hash-verified before copying. `PROVENANCE.json` records the archive SHA-256; `UPSTREAM_MANIFEST.sha256` and `UPSTREAM_README.md` preserve original provenance/documentation. That manifest describes the original archive, not files after these integration changes.

Local changes are limited to this directory:

- Added the explicit `app.labs.pretrade_ai` entry point, status, demo, and lab output containment.
- Kept dependencies, examples, config, schemas, and artifacts separate from the application.
- Changed the demo to backtest held-out rows; reject trained-model backtests overlapping the training-label embargo.
- Require timestamps/sources for identity evidence; reject duplicate input IDs and nonfinite numeric values.
- Reject unresolved mapping placeholders and ambiguous baseline eligibility; preserve explicitly mapped outcomes.
- Added regression/isolation tests and local setup documentation.

For the original package methodology, see `UPSTREAM_README.md`; for field requirements, see `MAPPING_REQUIRED.md`. Archive instructions to connect production are not part of this implementation.

## Forward paper book (2026-10-13)

- Starting cash $100; all-in buy $10; maximum gross sell/order $20; maximum two positions and $20 entry-cost exposure. No leverage.
- Entry must pass the unchanged supplied scorer, baseline gate and a quote no older than five seconds. Synthetic demo models and labeled historical rows cannot enter the forward book.
- Exit: fixed five-minute baseline, matching the source study's holding-period comparison. The scorer evaluates the current snapshot before every exit. Entry rejection does not trap an existing position. Missing price/liquidity or a different pool leaves the exit unresolved, never inventing proceeds.
- Every fill links to a persisted assessment and original opportunity. Transactions and balances commit atomically. Duplicate opportunity IDs cannot spend twice; a mint is entered only once. Single scanner enforced by OS lock.
- Costs are paper assumptions: 0.5% per leg plus $0.02 fixed and a constant-product impact estimate. They are not measured executable quotes and cannot establish profitability.
- Monthly profits above $100 are booked only when flat; losses are never refilled. No real withdrawals occur.
- The model is explicitly `rules-only-v1`; no trained-model prediction or promised win rate. The live adapter collects authority, history, holder and matched quote evidence; individual missing data still blocks entries.

See [PAPER_DEPLOYMENT.md](PAPER_DEPLOYMENT.md) for service isolation and deployment.

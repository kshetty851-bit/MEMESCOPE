# Pre-trade AI lab

An isolated, manually invoked **offline advisory lab**, imported from `MEMESCOPE-pretrade-ai-2.zip`. It scores candidate entries and compares selection decisions using supplied historical outcomes. It does not change any existing entry/exit strategy or wallet.

There is no API registration, scheduler, database connection, migration, exchange client, signer, wallet hook, or application startup integration. No backend dependencies were changed. The lab has its own virtual environment and writes only to its own `artifacts/` directory through the MEMESCOPE entry point.

## Website interface

The website route is `/pretrade-ai`, linked as **Pre-trade AI Lab** in navigation. It reviews locally opened advisory `scores.jsonl` exports: filter decisions, search candidates, and inspect score explanations. Files remain in the browser and are not uploaded or saved. A labeled synthetic sample demonstrates the interface. This page does not train models or connect a live candidate feed; those remain offline and disconnected.

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

No real MEMESCOPE data adapter was connected and no real market model was trained. Do not treat the supplied archive's historical research claims as independently verified findings. Existing production credentials and wallet configuration are not used.

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

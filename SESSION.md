# SESSION

Working state for MEMESCOPE. Rebuilt from the repository, not from memory.
Rules of engagement live in `CLAUDE.md`; architecture in `ARCHITECTURE_DECISIONS.md`.

## Current version

`0.8.0-rc1` (`backend/pyproject.toml`, `app/core/config.py`).
Branch: `opportunity-engine-foundation`. Last commit: `e60255c`.

## Completed sprints

| # | Sprint | Evidence |
|---|---|---|
| 1 | Discovery, enrichment, scoring engine, frontend surfaces | tagged history through `3069c12` |
| 2 | Platform stabilisation — autovacuum tuning, maintenance, audit corrections | `MEMESCOPE_AUDIT.md` §3.5, §6 |
| 3 | Decision layer — conviction, thesis, health, change | `e7b06b6`, `10c947f` |
| 4 | Analyst ensemble — six specialists behind one contract | `26ac040` |
| 5 | Radar sweep rotation + peak-vs-window fix | `14ea3e6`, `7715a15` |
| 6 | Watchlists, immutable event log, orchestrator + REST | `4c8e459`, `d38860f` |
| 7 | Opportunity Engine architecture, fresh graduation, near-graduation replay | `e60255c`, ADR §14a |

## Current sprint — Sprint 8: bonding-curve collection

Goal: land the on-chain input ADR §14a names as the only unblock for Near
Graduation. All uncommitted on `opportunity-engine-foundation`.

Done:

- `app/models/curve.py` + migration `20260803_0009_bonding_curve_snapshots`
- `app/services/curve/{pda,state,collector}.py` — local PDA derivation, account
  parse with invariants, batched `getMultipleAccounts` (100/call)
- `app/repositories/curve.py` — append-only snapshot writes
- Worker TX-3: `_collect_curves` runs before detection in `market/worker.py`,
  with its own transaction and its own counters
- `FEATURE_CURVE_COLLECTION_ENABLED` and friends in the `x-backend-env` anchor
- Tests: `test_curve_pda`, `test_curve_state`, `test_curve_collection`

- **Curve progress now reaches the providers.** `CurveSnapshotRepository.
  windows_for` batches the series; `as_of_progress` attaches, per observation,
  the newest curve reading taken at or before it — never carried backwards.
  Gated on `FEATURE_CURVE_COLLECTION_ENABLED` so a stopped series is reported
  absent rather than stalled. 9 new tests; suite 2887 passed at 91%.

Remaining:

- `make check` fails at `ruff format --check` across **33 files, 18 of them
  committed and untouched** — pre-existing drift, not this sprint's. `ruff
  check` and `mypy` are clean. Needs a repo-wide format commit of its own.
- The account layout in `services/curve/state.py` is still unverified against
  mainnet (quota). Invariants make a wrong layout yield no reading, not a
  wrong one — but the first live run is the real test.

## Sprint 9 — opportunity lifecycle scheduling (done)

`app/opportunities/scheduler.py`: `opportunity_review`, beat every 5 minutes,
calling the existing `review_expired()` and committing its own transaction. No
lock, matching `score_sweep` — transitions are pure functions of stored
timestamps, so a duplicate pass is a no-op. Beat registration and `include`
asserted. 7 new tests; suite 2894 passed.

Correction recorded: re-detection opens a new generation after **CLOSED**, not
after ARCHIVED — AD-09, and the live-status partial unique index is what
enforces it. Archival is a settling period, not a lock.

## Sprint 10 — provider analytics (done)

`app/opportunities/analytics.py` (pure derivations) +
`OpportunityRepository.provider_totals` (two grouped passes) +
`GET /api/v1/opportunities/providers`. Nothing stored, no migration. Precision
reports unavailable with a reason: nothing writes `REALISED`/`INVALIDATED`, so
it has no denominator until the realisation exit path ships with breakout.
18 new tests; suite 2912 passed.

## Sprint 11 — breakout provider (done)

`providers/breakout.py`, emitting `BREAKOUT` and `PRE_BREAKOUT` (mutually
exclusive). Price above its own trailing high on volume above the window's
trailing **median** — ADR §16's baseline question, settled by measurement:
median, not mean, and the current reading excluded from its own baseline.
Registered operational; TTLs and thresholds in the compose anchor.

Replay over 54,253 historical windows (800 tokens): 11 breakout, 126
pre-breakout (0.253% of windows), strength median 64, byte-identical on a
second pass. 25,887 windows unavailable — 20,252 no volume baseline, 5,635 no
price. That is the honest floor, not a defect.

## Sprint 12 — signal outcomes (done)

`opportunities/outcomes.py` (pure) + engine `_settle_outcomes` on the detection
path + migration `0010_outcomes` (two `event_kind` values only — the outcome
lives in the existing `status` column). No new state, no new column.

**Precision is defined over predictive signals only.** Fresh graduation and
breakout are factual: they report completed changes and cannot be wrong later,
so scoring them would publish 0.00 against providers that never forecast.
Their invalidations are counted as `contradicted` instead. Replay: pre-breakout
precision 4/13 = 0.31 over 800 tokens; deterministic across 2,009 assessments.

## Sprint 13 — RPC abstraction (done)

`services/rpc/`: `SolanaRPC` interface, `StandardSolanaRPC` (plain JSON-RPC,
any node), `HeliusRPC` (standard + DAS `getAsset`), registry mirroring the
market-provider pattern. `services/helius/client.py` is now an alias shim.
`SOLANA_RPC_PROVIDER=solana` runs the platform with **no Helius key**; the key
is required only when Helius is the configured provider.

Verified live against `api.mainnet-beta.solana.com`, no API key: `getSlot`,
`getMultipleAccounts`, and a real pump.fun curve account parsed.

**Curve layout is now verified against mainnet** (closes the Sprint 8 unknown):
on-curve accounts return `token_total_supply=1e15` and
`real_token_reserves=793_100_000_000_000` — both exactly the documented
pump.fun constants — and `complete_byte` sits at offset 48 as documented.

## Sprint 14 — curve parser finalization (done)

`services/curve/state.py`: the "virtual reserves never drain to zero"
invariant now scopes to `complete=0` only. A live graduated account zeroes all
four reserves on migration — that's a fact of completion, not a misread.
`_U64_MAX` sentinel check still applies unconditionally. Re-ran Sprint 13's
four real graduated accounts against mainnet: all 4 previously-refused reads
now parse, `complete=True`, `progress=1`. 5 new regression tests pinned to the
observed bytes (incl. the real 115/151-byte account lengths); 2978 passed.

## V1 redesign — Week 1, item 1 (done)

**Market data on the opportunity board.** Launch blocker #1 from the V1 spec:
the board carried no price, liquidity, volume or age, so a trader could read a
signal and had no way to evaluate it.

`MarketOut` (nullable) + `age_seconds` on `OpportunityOut`;
`latest_for_mints` and `price_as_of_for_mints` batched on the market
repository; `_context_for` resolves a whole page in three queries, not one per
card. 24h change is derived at read time from two stored readings — no
`price_change_24h` column, because a stored delta drifts from its source.

Absence is a first-class state: an unpriced token returns `market: null`, never
zero; a token younger than 24h returns `change_24h_pct: null`, never 0%.
8 new tests; suite 3001 passed. Verified live — 25 cards carrying real figures.

## Known blockers

- **Helius plan quota exhausted (HTTP 429).** Discovery is down and curve
  collection cannot run against the live chain. Not a bug; reported through
  `/api/v1/health/pipeline`. Everything in this sprint is written to be correct
  when quota returns.
- **Near graduation stays flag-off** until curve progress is proven to flow.
  Do not re-open the market-cap question — ADR §14a, closed with measurement.
- **pump.fun `liquidity_usd` is 100% null** (ADR 0002). Fix built, deployed and
  reverted the same day; still the largest signal-quality constraint.
- `review_expired` has no scheduled caller yet.

## Next sprint (not started — needs approval)

**Sprint 9: Breakout / pre-breakout provider** — ADR §15 step 3, now the next
buildable signal since step 2 waits on data. Introduces multi-observation
windows and the realisation exit path. Open question to settle with
measurement: the baseline for surge detection (ADR §16).

# MEMESCOPE — working notes for Claude

MEMESCOPE is an **opportunity intelligence platform**, not a token scanner. A
scanner answers "what exists"; this answers "what became interesting, and why
now". Every opportunity exists because something **changed** — the token may be
weeks old, but the signal must be new.

## Running anything

**Everything runs in Docker.** There is no local venv. Never run `pytest`,
`ruff`, `mypy` or `alembic` on the host — they are not installed.

```bash
make check            # everything CI runs
make test-backend     # docker compose exec -T backend pytest -q
make migrate          # alembic upgrade head
make migration-check  # alembic check — must be clean, CI gates it
make db-stats         # planner estimates vs actual (read-only)
```

Ad-hoc: `docker compose exec -T backend <cmd>`. The `-T` matters in scripts.

**`timeout` does not exist in this shell** (zsh, macOS). Don't prefix commands
with it — use the tool's own timeout parameter.

`./backend` is bind-mounted, so tests run against uncommitted code without a
rebuild. The API auto-reloads; **worker/scanner/enrichment do not** — restart
them to pick up changes.

## Layout

| Path | |
|---|---|
| `backend/app/api/`, `services/`, `repositories/`, `models/` | Classic layered core |
| `backend/app/{radar,exit_signals,events,analysts,health,opportunities}/` | Vertical slices, each owning its own api/service/repository |
| `backend/app/models/*.py` | **All** ORM models (imported in `models/__init__.py` or autogenerate can't see them) |
| `frontend/src/` | Next.js 15 App Router |

Two module conventions coexist deliberately. Domain types (dataclasses, enums)
live in the feature package; ORM tables live in `app/models/`.

## Architecture rules that are enforced, not suggested

- **`api/` never writes SQL.** `services/` never imports FastAPI. `core/`
  imports nothing app-specific. (`exit_signals/api.py` violates this — known,
  pre-existing, don't copy it.)
- **`get_db` owns the transaction.** Services and repositories call `flush()`,
  never `commit()`. Workers own their own sessions and commit explicitly.
- **Engines are pure.** `services/scoring`, `app/radar`, `app/analysts` and
  `app/opportunities` do no I/O, hold no clock, use no randomness — `now` is
  always a parameter. AST-parsing purity tests enforce this. It is what makes
  signals replayable over history.
- **The database is the guarantee, application checks are the optimisation.**
  Idempotency comes from unique indexes + `ON CONFLICT`, not from "check then
  insert".
- **Money is `NUMERIC`, never float.** Serialised as JSON strings; the frontend
  keeps them as strings until display. Timestamps are `timestamptz`, UTC.

## Product rules

- **Never estimate missing data.** A component with no source returns
  *unavailable with a reason* — see `/smart-money/{mint}`, which exists purely
  to say "not collected". Missing data is charged to `evidence`, never hidden.
- **Never a recommendation.** Explanations describe what was observed. No buy,
  sell, hold, or "consider". Tests assert this across analysts and explanations.
- **Prose is rendered server-side from stable reason codes**, never stored and
  never composed on the client. Rewording is a deploy, not a migration.
- **The permanent record is immutable.** `first_detected_at` / `detected_at`
  are written once. Failed calls stay visible (Hall of Lessons). An empty board
  is a truthful board — never "fix" it by relaxing admission.

## Traps that have already cost time

- **Partial index predicates must match the SQL SQLAlchemy emits.**
  `has_veto.is_(False)` compiles to `IS false`; Postgres will not prove that
  implies `= false`, so an index written with `=` is silently never used. Always
  `EXPLAIN` the ORM's own SQL, not a hand-written equivalent.
- **asyncpg caches query plans per connection.** After adding an index, restart
  the backend or you will measure the old plan and conclude the index failed.
- **`LIMIT` without a total `ORDER BY` causes starvation.** This livelocked the
  score sweep for days: the same heap-order rows came back every cycle. Always
  order deterministically, with a tiebreak.
- **Don't add an unconditional `count(*)` to an endpoint.** Two of them cost
  7.1ms against a 0.4ms ranking query on `/scores/top` and dominated it. Prefer
  `has_more`.
- **`TimestampMixin` indexes `created_at` on every table.** New tables must
  declare that index in their migration or `alembic check` fails.
- **`event_kind` is a native Postgres enum.** New kinds need
  `ALTER TYPE ... ADD VALUE IF NOT EXISTS` in a migration.
- **Migration filenames start with a date** → not importable as modules. Load by
  path if a test needs their constants.
- **Don't re-export the engine from a package `__init__`** if `app/models/*`
  imports that package's enums — it forms an import cycle.
- **Redis channels are namespaced by `ENVIRONMENT`** (`settings.token_channel`,
  not `TOKEN_EVENT_CHANNEL`). Before this, running `pytest` crash-looped the
  development enrichment worker.
- **Feature flags and cross-service settings belong in the `x-backend-env`
  anchor** in `docker-compose.yml`, never on one service. A contract test
  enforces it; this has gone wrong three times.
- `TokenRepository.insert_if_absent` returns `None` when the row already exists.

## Testing

~2,800 backend tests run in ~24s at **90% coverage**; 169 frontend tests.
Markers: `unit` (no external services), `integration` (real Postgres + Redis).

Tests isolate Postgres via a `*_test` database and roll back per test. Compose
contract tests **skip inside the container** (the repo root isn't mounted) — CI
runs them from the runner. Verify those changes by other means.

Prefer testing the *property* over the mechanism, and write the reason into the
docstring — the suite doubles as the record of why things are the way they are.

## Current state

Version `0.8.0-rc1`. Real data in the dev DB: ~24k tokens, 1.7M market
snapshots, 1M score-history rows.

- **Discovery is down.** Helius returns HTTP 429 — an exhausted plan quota, not
  a bug. The scanner escalates to ERROR and reports itself through
  `/api/v1/health/pipeline`.
- **Opportunity Engine is built and flag-gated off** (`FEATURE_OPPORTUNITY_ENGINE_ENABLED`).
  Two providers ship: fresh graduation (`pumpfun` → `pumpswap`) operational, and
  near graduation registered but **non-operational**. Detection rides enrichment
  writes; `review_expired` has no scheduled caller yet.
- **Near graduation is blocked on data, and the question is closed.** Replay over
  386 observed graduations showed `market_cap` on a bonding-curve pair does not
  track curve progress — 10% precision, 1.3% recall. **Do not re-investigate**;
  see `ARCHITECTURE_DECISIONS.md` §14a for the measurements and for the only two
  things that would make it worth revisiting.
- The pump.fun bonding-curve liquidity gap (100% null `liquidity_usd`) is the
  single biggest constraint on signal quality. See `docs/adr/0002` — the fix was
  built, deployed, and reverted the same day.

## Read before changing anything substantial

- `MEMESCOPE_AUDIT.md` — measured state, open risks, corrections
- `ARCHITECTURE_DECISIONS.md` — the Opportunity Engine architecture (**approved**;
  don't redesign, amend with a dated note if implementation disproves something)
- `docs/ARCHITECTURE.md` — layers, failure modes, data model
- `docs/adr/` — market provider abstraction, and the composite-provider incident

Comments in this codebase explain **why**, not what, and often record an
incident. Match that. If a decision looks odd, the reason is usually in the
comment above it or in an ADR.

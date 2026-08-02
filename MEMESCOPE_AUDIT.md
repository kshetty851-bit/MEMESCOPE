# MEMESCOPE — Engineering Audit

**Date:** 2026-08-02
**Repository:** `~/Projects/MEMESCOPE`
**HEAD:** `d38860f` (main) + 16 uncommitted paths
**Declared version:** `0.8.0-rc1`

Every figure in this document was measured against the repository and the
running local stack on the date above. Nothing is estimated or inferred.

---

## 1. Executive Summary

### Maturity: ~78% toward a public v1.0

| Dimension | Score | Basis |
| --- | --- | --- |
| Backend engineering | 92% | 90% test coverage, mypy clean on 148 files, layered discipline held |
| Data pipeline | 65% | Discovery **dead 4 days**; enrichment healthy; scoring sweep starved |
| Frontend | 70% | 15 pages ship, but 7 backend features have no UI |
| Operations | 55% | Deploy tooling exists, unexercised; no alerting on silent pipeline death |
| Product completeness | 60% | Core loop works; the signal it produces is thin (avg evidence 40.9/100) |

### Architecture health: strong, with one drift

The layer contract in `docs/ARCHITECTURE.md` (`api/` never writes SQL,
`services/` never imports FastAPI, `core/` imports nothing app-specific) is held
everywhere except `app/exit_signals/api.py`, which builds 6 SQLAlchemy
statements directly and imports a private symbol (`_days_since`) from
`app/radar/api.py`. Two organisational conventions coexist — classic layered
(`api/services/repositories`) and vertical slices (`radar/`, `exit_signals/`,
`events/`, `analysts/`) — undocumented but coherent.

### Code quality: excellent

All gates green, measured at audit time:

```
ruff        All checks passed
mypy        Success: no issues found in 148 source files
eslint      clean (--max-warnings=0)
tsc         clean
pytest      2,539 passed, 16 skipped, 90% coverage, 19.2s
vitest      169 passed, 18 files, 1.5s
```

Zero `TODO`/`FIXME`/`HACK`/`XXX` markers across 37,769 lines of source. Comments
explain *why*, not *what*. Two ADRs, one of which honestly records a production
failure and the revert.

### Production readiness: not ready — the blockers are operational, not architectural

Three live faults, all invisible to the container healthchecks:

1. **Discovery has been dead for 4 days.** The scanner is on reconnect attempt
   **959**, rejected with `HTTP 429` by Helius. Last token discovered
   `2026-07-29 13:19`. The container reports `Up 3 days`. Nothing escalates past
   `warning`.
2. **The enrichment discovery listener is in a crash loop.** A poison pub/sub
   message tears down the whole subscription (`worker.py:165`) instead of being
   skipped per-message.
3. **The scoring sweep is starved.** Every 15-minute cycle reports
   `requested: 200, scored: 0, skipped: 200` — 2,880 unscorable tokens sit
   permanently at the head of an unordered `LIMIT 200` query and consume the
   entire budget forever.

### Biggest strengths

- **Honesty as an architectural principle.** Gaps are declared, weighted, and
  charged to `evidence` rather than estimated. `/smart-money/{mint}` returns
  "unavailable, here's why" instead of 404ing or fabricating. This is rare and is
  the platform's most defensible asset.
- **Failure-mode engineering done up front.** Bounded queues,
  `FOR UPDATE SKIP LOCKED` leases, circuit breakers, full-jitter backoff,
  `ON CONFLICT DO NOTHING` as the *actual* idempotency guarantee with Redis
  `SET NX` as a mere optimisation.
- **Test suite that runs in 19 seconds at 90% coverage.** Purity tests
  (`test_radar_purity.py`, `test_scoring_purity.py`,
  `test_exit_signals_purity.py`) enforce that scoring is a pure function of
  stored data — which is what makes `rescore_tokens` possible at all.
- **`NUMERIC` end-to-end.** Money never touches a float, from `NUMERIC(38,18)`
  through JSON strings to display.

### Biggest technical risks

| # | Risk | Severity | Evidence |
| --- | --- | --- | --- |
| R1 | Silent pipeline death with no alerting | **Critical** | 959 reconnects, 4 days, zero escalation |
| R2 | The core signal is thin | **Critical** | avg coverage 44.6, avg evidence 40.9, **0 elite tokens**, only 2 "strong" of 20,481 |
| R3 | Scoring sweep livelock | **High** | 2,880 tokens permanently stuck |
| R4 | Uncommitted `/radar/discovered` is the slowest endpoint in the API | **High** | 3.95s measured; the `count(*)` alone is 1.97s |
| R5 | Test suite corrupts the running stack via shared Redis | **High** | FK violation in enrichment traced to an audit test run |
| R6 | pump.fun liquidity gap unclosed; the fix was reverted | **High** | 100% null `liquidity_usd` on pumpfun snapshots (219/219 in 2h) |
| R7 | ~~Autovacuum has **never run** on the two largest tables~~ — **overstated, corrected in Sprint 2** | Low | See the correction below |

---

## 2. Completed Features

### Authentication — Complete

Two-token design: 15-min in-memory JWT access token + 48-byte httpOnly refresh
cookie scoped to `/api/v1/auth`, SHA-256 digest only in the DB. Rotation with
reuse detection — presenting a revoked token revokes every session for that
user. Redis `jti` denylist with self-expiring TTL.

- **Files:** `core/security.py`, `services/auth_service.py`,
  `api/v1/endpoints/auth.py`, `models/refresh_token.py`, `api/deps.py`
- **Dependencies:** Redis (denylist), Postgres
- **Endpoints:** 5 · **Coverage:** 84% (auth.py), 100% (security.py)

### Users — Complete

Profile read/update, password change with full session revocation.

- **Files:** `api/v1/endpoints/users.py`, `services/user_service.py`,
  `repositories/user.py`
- **Endpoints:** 3 · **Coverage:** 77% (user_service.py)

### Scanner / Discovery — Complete but currently DOWN

Helius `logsSubscribe`, `InitializeMint` pre-filter dropping 99.9%, bounded
2000-item queue that sheds newest on overflow, N workers doing `getTransaction`
+ DAS `getAsset` with independent retry ladders, `ON CONFLICT DO NOTHING`, Redis
fan-out to every API process.

- **Files:** `services/scanner/scanner.py` (372L), `services/scanner/parser.py`
  (253L), `services/helius/client.py`, `scanner_main.py`, `core/events.py`
- **Dependencies:** Helius WebSocket + RPC, Redis pub/sub, Postgres
- **Data:** 24,196 tokens (23,319 resolved / 877 pending metadata), all
  `source_program = pump.fun`
- **Coverage:** 60% scanner.py, 93% parser.py — the uncovered lines are the
  reconnect/RPC paths, i.e. exactly the ones failing in production

### Market Enrichment — Complete and healthy

DB work queue with `FOR UPDATE SKIP LOCKED` + lease, 4-tier adaptive refresh
(30s/5m/30m/6h by age), batches of 30 mints, dual backoff (exponential on
failure, linear on empty — an unindexed pool is not an error), circuit breaker
(5 fails → open 60s → half-open probe → 2 successes to close), append-only
snapshots.

- **Files:** `services/market/` (worker 315L, service 256L, scheduler,
  circuit_breaker, query_service), `providers/` (base, dexscreener 287L,
  geckoterminal 279L, composite 258L, rate_budget, registry),
  `enrichment_main.py`, `repositories/market.py`
- **Dependencies:** DexScreener, GeckoTerminal (opt-in), Redis, Postgres
- **Data:** 1,723,011 snapshots (803MB), 24,191 active / 5 dead-lettered
- **Coverage:** 92–100% on providers, 58% on worker.py

### AI Scoring Engine — Complete

Deterministic weighted model, no ML/LLM in the path. Six components (liquidity,
market_risk, momentum, survival, trade_flow, valuation), evidence/coverage/
confidence tracking, veto gate, elite streak, materiality-gated history writes,
published weights, model registry for versioned rescoring.

- **Files:** `services/scoring/` (26 files: engine 384L, service 482L,
  query_service 448L, features 272L, explain 265L, + components/ and models/),
  `models/score.py`, `repositories/score.py` (529L), `workers/scoring_tasks.py`
- **Dependencies:** market snapshots only (pure function of stored data)
- **Data:** 20,481 scores, 1,031,417 history rows (1.7GB)
- **Coverage:** **100% across every scoring module** — the best-tested subsystem
  in the repo
- **Endpoints:** 4

### Opportunity Radar — Complete

Tracks projects of any age. Returns measured from MEMESCOPE's first detection,
never token launch. First detection immutable, records append-only, failures
never hidden. Rotation sweep across 48 buckets covers the whole eligible
universe. Categories: elite / breakout / early_momentum / undervalued.

- **Files:** `radar/` (16 files: repository 591L, api 407L, service 349L, models
  258L, + scorer, momentum, technical, community, health, detector,
  achievements, explain, normalise, schemas, scheduler), `models/radar.py`
- **Dependencies:** market snapshots, scoring, analysts
- **Data:** 40 tracked (1 elite, 17 breakout, 20 early momentum, 3 undervalued),
  524 snapshots, 12 achievements
- **Coverage:** 56% api.py, rest high · **Endpoints:** 6 (+1 uncommitted)

### Exit Watch + Permanent Record — Complete

Seven checkable signals, two permanently declared unavailable. Explicitly never
a sell signal. Hall of Fame ranks by peak, Hall of Lessons by current — one
page, one toggle.

- **Files:** `exit_signals/` (api 388L, detector 259L, explain, models, schemas,
  smart_money)
- **Coverage:** 38% api.py (the weakest API module) · **Endpoints:** 6

### Analyst Ensemble — Complete

Six specialist analysts (holders, lifecycle, liquidity, momentum, research,
risk) behind one contract, plus orchestrator. Read-only, pure, over stored
observations. Publishes its own weights.

- **Files:** `analysts/` (7 files, orchestrator 253L),
  `api/v1/endpoints/analysts.py`, `models/intelligence.py`
- **Data:** `analyst_reading_cache` 20 rows · **Coverage:** 59% (endpoint) ·
  **Endpoints:** 2

### Watchlists + Event Intelligence — Backend complete, zero frontend

User-scoped watchlists (SQL-scoped, not app-filtered), immutable event log,
change detection diffing fresh analyst readings against cached previous ones,
"since your last visit" brief.

- **Files:** `events/` (repository 387L, detector 348L, orchestrator 215L,
  scheduler), `api/v1/endpoints/watchlists.py` (304L),
  `api/v1/endpoints/events.py` (258L)
- **Data:** 3 watchlists, 1 item, 20 events
- **Coverage:** **28% watchlists.py — the lowest-covered module in the repo**
- **Endpoints:** 13 · **Frontend consumers: 0**

### Clone Risk / Identity — Complete

Duplicate project-name detection requiring a cross-token scan, so genuinely
server-side.

- **Files:** `services/identity.py`, `api/v1/endpoints/identity.py`,
  `schemas/identity.py` · **Endpoints:** 2

### Frontend — Complete for shipped scope

Next.js 15 / React 19 / Tailwind v4 / Zustand / TanStack Query. In-memory access
token, single shared refresh promise so six parallel 401s trigger one rotation.
15 pages, 62 components, 12 hooks, 1 store, 22 lib modules.

### Infrastructure / Docker / Deployment — Complete, unexercised in production

8 compose services, dev + prod overlays, Caddy edge,
backup/restore/deploy/rollback/health-check scripts, pre-commit, CI with lint +
typecheck + migration-drift gate (`alembic check`) + Trivy scan + image builds.

- **Files:** `docker-compose.yml`, `docker-compose.prod.yml`,
  `docker/{caddy,nginx,postgres}`, `scripts/*.sh`, `.github/workflows/ci.yml`,
  `Makefile`
- **Note:** `docker/nginx/nginx.conf` superseded by Caddy, retained per prior
  audit

### Analytics — Not wired

`frontend/src/lib/analytics.ts` (61L) exists and is **imported by nothing**.

---

## 3. Partially Implemented Features

### 3.1 Pump.fun Radar admission stage — uncommitted, ~70% done

**Current implementation:** `services/pumpfun_radar.py` (98L) +
`GET /radar/discovered` + `RadarCandidate`/`RadarCandidateSignals` models + 2
repository queries + Celery task behind `FEATURE_PUMPFUN_RADAR_ENABLED` (default
off) + 6 settings + 10 passing tests. Read-only over persisted scanner/enrichment
output — correctly refuses to re-fetch or re-score.

**Missing work:**

- **Performance.** Measured at **3.95s**, the slowest endpoint in the API. Root
  cause confirmed by `EXPLAIN ANALYZE`: the paged query short-circuits the window
  function via `Run Condition` (36ms), but the unbounded `count(*)` cannot — it
  scans all 1,723,011 snapshot rows in **1.97s**, and the outer
  `ORDER BY captured_at DESC` costs another ~2s.
- `source_program` filter is currently a no-op — 100% of `discovered_tokens` are
  already pump.fun. The supporting index `ix_discovered_tokens_source_program`
  has 9 lifetime scans.
- No `docs/API.md` entry, no `docs/api/openapi.json` regeneration.
- `signals` extension point is declared but no stage populates it.
- No frontend.

**Effort: 1–2 days**

### 3.2 Composite market provider — built, verified, reverted

**Current implementation:** Full `CompositeProvider` with pool-keyed
GeckoTerminal secondary, 99% test coverage, ADR-0002 documenting the field choice
with measured agreement data (median 1.005x on pool-keyed vs 0.49–0.97x on
mint-keyed).

**Missing work:** Placement. Enabled on the live stack 2026-07-30 and reverted
the same day — it stalled enrichment completely (0 snapshots for ~1h; 21 within a
minute of reverting). Cause: GeckoTerminal's 25-calls/min budget forces sleeps
inside every batch under `ENRICHMENT_CONCURRENCY=4`, and httpx timeouts are
wall-clock, so a saturated event loop expires requests whose responses already
arrived. Needs the fill moved **off** the enrichment request path (separate
backfill worker) or a hard per-batch time budget.

**Effort: 3–5 days.** This is the single highest-value unblock — see §4.

### 3.3 Watchlists — backend 100%, frontend 0%

7 endpoints, fully auth-scoped, 28% covered. `frontend/src/lib/watchlist.ts`
(213L) is an orphaned Phase-12 localStorage implementation superseded by this
API, imported by nothing.

**Effort: 2–3 days** (UI + delete the orphan)

### 3.4 Event Intelligence — backend 100%, frontend partial

6 endpoints. `/brief` and `/brief/changes` are consumed by the Command page.
`/events`, `/events/{id}`, `/events/token/{mint}`, `/mission-log` have no
consumer.

**Effort: 1–2 days**

### 3.5 Score sweep reconciliation — works, but livelocked

`mints_without_scores` (`repositories/score.py:141`) has **no `ORDER BY`** under
its `LIMIT`. Postgres returns the same heap-order rows each cycle. All 200 are
unscorable (no market window), so all 200 are skipped and re-selected forever.
2,880 tokens are permanently stuck; the sweep has made zero progress in days. The
enrichment fast path still scores normally (`max(evaluated_at)` is current), so
this is a degraded safety net rather than total scoring failure — but 19,370 of
20,481 score rows are >1h stale.

**Effort: 2 hours** (add ordering + skip-window exclusion)

### 3.6 Exit Watch API layer — functional, off-contract

6 inline SQLAlchemy statements in `exit_signals/api.py` and
`from app.radar.api import _days_since`. Works, tested, but breaches the
documented layer rule and couples two modules through a private symbol.

**Effort: 1 day** (extract `ExitSignalsRepository`, promote `_days_since`)

---

## 4. Missing Features

### Critical

| Feature | Why | Notes |
| --- | --- | --- |
| **Pipeline liveness alerting** | Discovery died 4 days ago and nothing noticed. The scanner container is `Up`, has no healthcheck, and 959 consecutive failures never escalate past `warning`. | Cheapest fix: a `/ready`-style staleness probe on `max(discovered_at)` + a healthcheck on the scanner service. |
| **Bonding-curve liquidity source** | `liquidity_depth` carries 0.20 of model weight and is null for **100%** of pump.fun snapshots. This one gap is why avg coverage is 44.6 against a 65 ceiling, why avg evidence is 40.9, and why **zero tokens have ever reached elite**. | Either fix composite placement (§3.2) or derive reserves on-chain via Helius. ADR-0002 names the latter as the correct long-term answer. |
| **Helius plan capacity** | The 429s are a quota wall, not a bug. No amount of backoff fixes an exhausted plan. | Product decision, not engineering. |

### High

- **Watchlist UI** — 7 endpoints with no consumer; the "portfolio" roadmap item
  is half-built already.
- **Alerts / delivery channel** — the event log and change detection exist;
  nothing delivers them.
- **Latest-snapshot pointer** — kills the `DISTINCT ON`/window-function cost
  behind both `/market/trending` (2.23s) and `/radar/discovered` (3.95s) in one
  change.
- **Redis namespace isolation for tests** — the suite isolates Postgres
  (`memescope_test`) but publishes to the *shared*
  `memescope:tokens:discovered` channel. Running `pytest` crashes the live
  enrichment worker. Reproduced during this audit.
- **Rotation engine** — lead/lag over stored series; roadmap says computable
  today, and it is.

### Medium

- Per-message error isolation in the discovery listener (`worker.py:165`)
- Autovacuum/analyze tuning on the two large tables
- Drop ~19MB of never-scanned indexes (§6)
- Auth on the intelligence surface — every endpoint except watchlists/events is
  public
- OpenTelemetry (explicitly deferred in `docs/ARCHITECTURE.md`)
- `docs/API.md` + `openapi.json` regeneration
- E2E tests (Playwright) — currently zero

### Low

- Email verification (`is_verified` column already exists)
- Read replicas
- Multi-chain
- Delete `app/utils/` (empty package)

---

## 5. Architecture Review

```
                        Helius WebSocket (logsSubscribe)
                                    │  ✗ HTTP 429 — DOWN 4 DAYS
                                    ▼
                      ┌───────────────────────────┐
                      │  SCANNER  (own container) │
                      │  InitializeMint pre-filter│
                      │  bounded queue (2000)     │
                      │  N workers → getTx + DAS  │
                      └─────────────┬─────────────┘
                                    │ ON CONFLICT DO NOTHING
                                    ▼
                          discovered_tokens (24,196)
                                    │
                    ┌───────────────┴────────────────┐
                    │ Redis pub/sub                  │ DB work queue
                    │ memescope:tokens:discovered    │ (durable, recurring)
                    ▼                                ▼
        ┌───────────────────────────────────────────────────┐
        │  ENRICHMENT  (own container)   ⚠ listener crashloop│
        │  claim_due: FOR UPDATE SKIP LOCKED + lease        │
        │  4-tier cadence · batches of 30                   │
        │  MarketDataProvider ABC → DexScreener             │
        │    retry · circuit breaker · rate budget          │
        └───────────────────────┬───────────────────────────┘
                                ▼
              token_market_snapshots (1,723,011 · append-only)
                                │
        ┌───────────────────────┼───────────────────────────┐
        ▼                       ▼                           ▼
┌───────────────┐   ┌────────────────────┐   ┌──────────────────────┐
│ SCORING       │   │ RADAR              │   │ ANALYSTS (6 pure)    │
│ 6 components  │   │ scorer · momentum  │   │ holders · lifecycle  │
│ evidence      │──▶│ technical · health │◀──│ liquidity · momentum │
│ veto · elite  │   │ community · detect │   │ research · risk      │
│ pure function │   │ 48-bucket rotation │   └──────────┬───────────┘
└───────┬───────┘   └─────────┬──────────┘              │
        │                     │                          ▼
        │                     │              ┌──────────────────────┐
        │                     └─────────────▶│ EVENTS               │
        │                                    │ detector · immutable │
        │                                    │ log · watchlists     │
        │                                    └──────────┬───────────┘
        │                                               │
        ▼                                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  FastAPI  /api/v1  — 49 paths, 53 operations + 1 WebSocket       │
│  ProxyHeaders → RequestContext → TrustedHost/CORS/GZip           │
│  → SecurityHeaders → RateLimit → Router → Service → Repository   │
└───────────────────────────────┬──────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Next.js 15 · React 19 · TanStack Query · Zustand · Tailwind v4   │
│  15 pages · 62 components · in-memory token + httpOnly refresh   │
└──────────────────────────────────────────────────────────────────┘

    CELERY BEAT ─┬─ score-sweep       */15   ⚠ starved (0 scored)
                 ├─ radar-sweep       */15   ✅ 987 evaluated/cycle
                 ├─ event-cycle       3,18,33,48
                 ├─ pumpfun-scan      */15   (flag off)
                 ├─ prune-history     03:30
                 └─ purge-tokens      03:00
```

### Layer by layer

| Layer | Responsibility | Health |
| --- | --- | --- |
| **Discovery** | Owns creation facts. Own container because a stream consumer inside gunicorn means one duplicate subscription per worker. Idempotency is a DB guarantee, not app code. | DOWN — quota |
| **Enrichment** | Owns market facts. DB queue rather than Redis queue because the work is *recurring*, not one-shot — `next_refresh_at` expresses that directly and survives restarts. `fetch_many` is the provider primitive, not an optimisation. | Working, listener unstable |
| **Provider abstraction** | Nothing above `providers/` sees vendor JSON. Proven by ADR-0002: adding a whole second vendor changed no service, repository, schema, migration, endpoint or component. | The strongest boundary in the codebase |
| **Scoring** | Pure function of stored data — which is *why* `rescore_tokens` under a new model version is possible at all. Enforced by `test_scoring_purity.py`. | 100% covered |
| **Radar** | Independent cadence from discovery. Returns measured from first detection, never launch. Append-only, failures never hidden. | Healthy |
| **Analysts / Events** | Read-only overlays. Events deliberately run 3 minutes *after* the radar sweep so they diff fresh readings against cached previous ones. | Correct, under-consumed |
| **API** | Versioned, response-modelled, request-id threaded. Transaction boundary owned by `get_db`; services `flush()`, never `commit()`. | One module off-contract |
| **Frontend** | Renders backend state, never fabricates. Money stays a string until display. | 7 features unconsumed |

---

## 6. Database Review

15 tables, 7 migrations, head `7969db20724a`, no drift (CI gates
`alembic check`).

| Table | Rows | Size | Stores |
| --- | ---: | ---: | --- |
| `token_score_history` | 1,031,417 | **1,766 MB** | Append-only score timeline, materiality-gated writes |
| `token_market_snapshots` | 1,723,011 | **803 MB** | Append-only market observations — the asset that makes backtesting possible |
| `discovered_tokens` | 24,196 | 22 MB | Creation facts; `mint_address` is the natural key |
| `token_enrichment_state` | 24,196 | 16 MB | Scheduler work queue; `next_refresh_at` drives every claim |
| `token_scores` | 20,481 | 24 MB | Current score per token (1:1) |
| `radar_snapshots` | 524 | 808 kB | Radar score timeline |
| `radar_tokens` | 40 | 184 kB | Tracked opportunities, immutable first detection |
| `intelligence_events` | 20 | 80 kB | Immutable event log |
| `analyst_reading_cache` | 20 | 96 kB | Previous analyst readings for change detection |
| `radar_achievements` | 12 | 72 kB | Milestone records |
| `users` / `refresh_tokens` | 7 / 7 | 264 kB | Auth |
| `watchlists` / `watchlist_items` | 3 / 1 | 176 kB | User watchlists |

### Unused tables

**None.** Every table has rows and a live consumer. `watchlist_items` (1 row)
and `intelligence_events` (20 rows) are underused rather than unused.

### Duplicate data

- `mint_address` is denormalised onto `token_market_snapshots`, `token_scores`,
  `token_score_history`, `token_enrichment_state`, `radar_snapshots`.
  **Deliberate and correct** — history queries need no join.
- `token_scores` vs `token_score_history` — current-vs-timeline split, standard.

### Autovacuum has never run

```
last_autovacuum | last_autoanalyze |        relname
----------------+------------------+------------------------
                |                  | discovered_tokens
                |                  | token_market_snapshots
```

`pg_stat_user_tables` reported `discovered_tokens` at **0 live rows** when the
real count is 24,196, and `token_market_snapshots` at 17,777 against a real
1,723,011.

> **Correction (Sprint 2, 2026-08-02).** The conclusion drawn from this — that
> the planner was choosing plans from row estimates wrong by two orders of
> magnitude, and that this contributed to the trending/discovered latency — was
> **wrong**, and the numbers above are the reason why.
>
> `n_live_tup` is an activity counter that is discarded on an unclean shutdown.
> The planner does not read it. It reads `pg_class.reltuples`, which was within
> **9%** of the truth on every table, with column statistics present and
> plausible (`token_market_snapshots.captured_at` correlation 0.99999,
> `n_distinct` sane). The NULL `last_autovacuum` timestamps reflect lost
> counters, not absent statistics.
>
> Measured directly: running `ANALYZE` across all five tables moved every drift
> factor to 1.00 and changed **no** endpoint latency — `/market/trending`
> 1.91 s → 1.92 s, `/radar/discovered` 3.60 s → 3.62 s, `/scores/top`
> unchanged. The slowness is query shape, exactly as §3.1 and the optimisation
> list say; statistics were never a contributor.
>
> Sprint 2 still ships the per-table autovacuum tuning and the maintenance
> command, but as prevention against future drift on two continuously growing
> tables — not as a fix for a problem that existed. Severity downgraded from
> Medium to Low.

### Never-scanned indexes (~19 MB reclaimable)

| Index | Size | Scans | Note |
| --- | ---: | ---: | --- |
| `ix_token_scores_ranking` | 7.1 MB | **0** | Built for `/scores/top`, which does not use it — open finding #4 from the July audit |
| `ix_token_scores_ranking_hot` | 6.9 MB | **0** | Same |
| `ix_discovered_tokens_signature` | 3.7 MB | **0** | |
| `ix_discovered_tokens_discovered_at_desc` | 976 kB | **0** | Redundant with `ix_discovered_tokens_discovered_at` (21 scans) |
| `ix_discovered_tokens_creator_address` | 824 kB | **0** | Awaits a "creator history" feature |
| `ix_discovered_tokens_status_discovered` | 768 kB | **0** | |
| `ix_discovered_tokens_created_at` | 552 kB | **0** | Redundant with `discovered_at` |
| `ix_token_enrichment_state_created_at` | 1.6 MB | **0** | |
| `ix_discovered_tokens_block_time` | 488 kB | **0** | *Will* be used by `/radar/discovered` |
| `pk_token_market_snapshots` | 70 MB | **0** | Cannot drop, but it is 70MB of pure write cost |

### Working hard (keep)

`ix_snapshots_mint_captured_desc` 304,098 scans ·
`ix_score_history_mint_evaluated` 245,186 ·
`ix_discovered_tokens_mint_address` 495,006 · `ix_enrichment_due` 8,695

### Optimisations, ranked

1. **`VACUUM ANALYZE` the two large tables and tune autovacuum** — hours of
   effort, potentially the largest single win.
2. **Latest-snapshot pointer** — a `token_latest_snapshot` table or a partial
   index removes the window function from `/market/trending` *and*
   `/radar/discovered` at once.
3. **Composite `(source_program, block_time)` index** for `/radar/discovered`.
4. **Partition `token_score_history` by month** — 1.77 GB with 30-day retention
   means the daily prune rewrites rather than drops. `DROP PARTITION` is O(1).
5. **Drop the 19 MB of dead indexes** (keep `block_time`, keep
   `creator_address` if creator history is on the roadmap).

---

## 7. API Review

**49 paths · 53 operations · 1 WebSocket.** Live schema version `0.8.0-rc1`.

### Health (2) — complete

`GET /live` (never touches a dependency) · `GET /ready` (Postgres + Redis, 503
when down)

### Auth (5) — complete

`POST /auth/{register,login,refresh,logout,logout-all}`

### Users (3) — complete

`GET|PATCH /users/me` · `POST /users/me/password`

### Tokens (3 + WS) — complete

`GET /tokens` · `/tokens/latest` · `/tokens/{mint}` · `WS /tokens/stream`

### Market (3) — complete, performance issue

`GET /tokens/{mint}/market` · `/tokens/{mint}/history` · `/market/trending`
**2.23s**

### Scores (4) — complete, index issue

`GET /scores/{mint}` · `/scores/{mint}/history` · `/scores/top` (37ms, misses
its 14MB of ranking indexes) · `/scores/model`

### Radar (7, one uncommitted) — complete, performance issue

`GET /radar` (17ms) · `/radar/{mint}` · `/radar/{mint}/history` ·
`/radar/categories` · `/radar/leaderboard` · `/radar/performance` (3ms) ·
**`/radar/discovered` 3.95s — uncommitted**

### Intelligence (6) — complete

`GET /exit-watch` · `/exit-watch/{mint}` · `/exit-watch/model` ·
`/hall-of-fame` · `/hall-of-lessons` · `/leaderboard` · `/smart-money/{mint}`
*(deliberately always-unavailable, with reason — good design, not a stub)*

### Analysts (2) — complete

`GET /analysts/{mint}` · `/analysts/model`

### Identity (2) — complete

`GET /identity/{mint}` · `POST /identity/batch`

### Watchlists (7) — backend complete, 0 frontend consumers

`GET|POST /watchlists` · `PATCH|DELETE /watchlists/{id}` ·
`GET|POST /watchlists/{id}/tokens` · `DELETE /watchlists/{id}/tokens/{mint}` ·
`GET /watchlists/{id}/events`

### Events (6) — 2 of 6 consumed

`GET /brief` (used) · `/brief/changes` (used) · `/events` · `/events/{id}` ·
`/events/token/{mint}` · `/mission-log`

### Deprecated

**None.** No `deprecated=True`, no versioned duplicates. Clean surface.

### Missing endpoints

- Alert subscription/delivery CRUD
- Portfolio / PnL
- Rotation engine reads
- Admin/ops (requeue dead-lettered tokens, force rescore, pipeline status)
- **A pipeline-health endpoint** — nothing exposes "when did discovery last see
  a token", which is exactly the fact that would have caught R1

### Auth posture

Every intelligence endpoint (tokens, market, scores, radar, exit-watch,
analysts, identity) is **unauthenticated**. Only watchlists (10 refs) and events
(3 refs) are user-scoped. Rate limiting is the only gate: 120 req/60s, keyed by
token *or IP*. For a product whose entire value is the intelligence, this is a
business-model decision that should be made explicitly rather than inherited.

---

## 8. Background Workers

### Scanner (`scanner` container) — DOWN

Long-lived stream consumer in its own container. Full-jitter exponential backoff
— deliberately, so that when Helius recovers, every client does not retry in
lockstep and knock it over again.

```
scanner_reconnect  attempt=959  delay_seconds=46.28
error='server rejected WebSocket connection: HTTP 429'
```

**Assessment:** the backoff is behaving exactly as designed. The design gap is
that it retries **forever at `warning` level with no ceiling and no
escalation**, and the compose service has **no healthcheck**. A quota exhaustion
is indistinguishable from a transient blip. 4 days of zero discovery went
unnoticed.

### Market Worker (`enrichment` container) — working, listener unstable

Two intakes: a Redis fast path (enrol on discovery) and the durable DB queue
(every subsequent refresh), plus a 5-minute backfill sweep. That sweep is
load-bearing — a startup-only version left 1,411 tokens stranded in live
verification.

**Defect (`worker.py:129–178`):** the inner `try` catches only
`(ValueError, TypeError, AttributeError)` on JSON parsing. Any database error
from `register_token` escapes to the *outer* handler, which tears down the
entire pub/sub subscription and reconnects with backoff. One poison message
costs the whole listener.

Reproduced during this audit — the test suite isolates Postgres but shares
Redis, so `pytest` published a mint whose `discovered_tokens` row exists only in
`memescope_test`:

```
enrichment_listener_reconnect attempt=1
  ForeignKeyViolationError: Key (token_id)=(b941998f-…) is not present in table "discovered_tokens"
```

Two independent bugs there: no per-message isolation, and no Redis namespacing
between test and dev.

### Celery tasks

| Task | Schedule | Status |
| --- | --- | --- |
| `radar_sweep` | */15 | 987 evaluated, 41 tracked, 2.2s |
| `score_sweep` | */15 | **`requested:200 scored:0 skipped:200` every cycle** |
| `event_cycle` | 3,18,33,48 | Healthy |
| `pumpfun_radar_scan` | */15 | Flag off |
| `prune_score_history` | 03:30 | 30-day retention, 1.77 GB — rewrites rather than drops |
| `purge_expired_refresh_tokens` | 03:00 | Healthy |

### Retry logic — well-differentiated

| Path | Strategy |
| --- | --- |
| Helius WS | Exponential + **full jitter**; clean connection resets the ladder |
| Transaction not queryable | Bounded polls (`SCANNER_TX_FETCH_ATTEMPTS`) |
| DAS metadata | Bounded polls, then stored `pending` — metadata never blocks discovery |
| Provider 5xx/timeout/429 | Exponential + jitter, counts toward breaker |
| Provider 4xx | **Not retried** — our bug, would fail identically |
| Token with no pool | **Not an error.** Linear backoff capped at the mature interval |
| Repeated token failure | Dead-lettered at 10, retained and requeueable (5 tokens currently) |
| Worker crash | Lease expiry returns tokens to the queue |

### Redis usage

`memescope:tokens:discovered` (discovery fan-out) · `memescope:scores:changed`
(score events) · rate-limit counters · JWT `jti` denylist · Celery broker +
result backend · scanner `SET NX` dedupe (optimisation only — the unique index
is the guarantee).

**Gap:** no environment namespacing on any channel. Dev, test and any future
staging on the same Redis will bleed into each other, as demonstrated above.

---

## 9. Frontend Review

**17,491 LOC · 15 pages · 62 components · 12 hooks · 1 store · 22 lib modules ·
18 test files**

### Pages

| Route | LOC | Status |
| --- | ---: | --- |
| `/system` | 421 | Pipeline telemetry |
| `/tokens/[mint]` | 409 | Full detail: thesis, health, timeline |
| `/about` | 325 | Complete |
| `/command` | 314 | Primary surface — Today's Opportunities, mission brief |
| `/` (landing) | 304 | Complete |
| `/radar/[mint]` | 291 | Complete |
| `/hall-of-fame` | 243 | Fame/Lessons toggle |
| `/feed` | 235 | Observatory, live WS |
| `/division` | 218 | Analyst ensemble |
| `/radar` | 199 | Complete |
| `/track-record` | 195 | Complete |
| `/exit-watch` | 182 | Complete |
| `/register` `/login` | 197 | Complete |
| `/dashboard` | 9 | Redirect to `/command` |

Plus `error.tsx`, `not-found.tsx`, `loading.tsx`.

### Components (62)

`brand/` 9 (universe, ai-core, mascot, sigils, space-field) · `decision/` 10
(conviction, thesis, health, timeline, scoreboard, mission-brief, clone-risk) ·
`ui/` 10 · `layout/` 3 · `alpha/` 3 · `token/` 3 · `sentinel/` 2 · `squad/` 1 ·
`observatory/` 1 · `radar/` 1

### Stores

One: `auth-store.ts` (119L, Zustand). Server state deliberately lives in
TanStack Query — correct split, no duplication.

### Hooks (12)

`use-auth` · `use-radar` · `use-scores` · `use-market-data` ·
`use-token-stream` (WS) · `use-intelligence` · `use-identity` ·
`use-observatory-log` · `use-observatory-mode` · `use-reduced-motion` ·
`use-api-latency` (unused)

### Dashboard status: complete

`/dashboard` redirects to `/command`, which leads with Today's Opportunities,
mission brief, conviction language, and since-last-visit changes. This is the
most product-complete surface in the app.

### Radar status: complete for the Opportunity Radar

List + detail + scoreboard + achievements + history, wired to all 6 committed
endpoints. The uncommitted `/radar/discovered` has **no** frontend.

### Dead code — 9 modules, 1,100 lines, imported by nothing

```
components/sentinel/sentinel-panel.tsx     219
components/observatory/observatory-log.tsx 233
lib/watchlist.ts                           213
components/layout/telemetry-bar.tsx        164
components/brand/ambient-field.tsx         125
lib/analytics.ts                            61
components/ui/trading-status-badge.tsx      37
components/ui/card.tsx                      27
hooks/use-api-latency.ts                    21
```

`lib/watchlist.ts` is the notable one: a complete localStorage watchlist with
reason-tracking, superseded by the Phase-17 backend API that itself has no UI.
Two implementations, zero shipped.

### Missing screens

Watchlists · Alerts · Settings/profile · Mission log · Full event history ·
Pump.fun discovery candidates · Rotation

---

## 10. Testing

### Backend — excellent

```
2,539 passed · 16 skipped · 19.22s · 90% coverage (7,148 statements, 750 missed)
```

Skips are legitimate: `test_compose_env_contract.py` cannot read
`docker-compose.yml` from inside the container.

**Perfect coverage (100%):** every scoring module (26 files), circuit breaker,
provider base/rate_budget/registry, market scheduler, market query_service.

**Weakest:**

| Module | Coverage | Note |
| --- | ---: | --- |
| `enrichment_main` / `scanner_main` / schedulers | 0% | Entrypoints — acceptable |
| `endpoints/watchlists.py` | **28%** | 304 lines, newest feature, real gap |
| `exit_signals/api.py` | 38% | Where the SQL-in-API lives |
| `middleware/rate_limit.py` | 42% | Security-relevant |
| `endpoints/identity.py` | 56% | |
| `radar/api.py` | 56% | |
| `market/worker.py` | 58% | **The crash-looping listener is in the uncovered range (131–178)** |
| `scanner/scanner.py` | 60% | **The failing reconnect path is in the uncovered range (136–165)** |

The correlation is not a coincidence: both live production failures sit in the
two lowest-covered runtime modules.

### Integration — 20 files

auth flow, enrichment↔scoring pipeline, enrichment worker, event
orchestrator/repository, health, market API/repository, pump.fun radar, radar
pipeline, scanner, score repository, scores API, scoring service/tasks, token
repository, token stream WS, tokens API, users.

### Unit — 40 files

Notably three **purity** suites enforcing that scoring, radar and exit signals
are pure functions of stored data.

### Frontend — adequate for logic, absent for UI

```
18 files · 169 tests · 1.51s
```

Well covered: `format`, `radar`, `sentinel` (21 tests), `conviction`, `scores`,
`mission`, `thesis`, `camera`, `market-quality`, `research-priority`,
`scoreboard`, `feedback`, `api-client`, `middleware`, 3 hooks.

**Gap:** 1 of 62 components tested (`alpha-bar`). 0 of 15 pages. No E2E.

### Missing tests

- Discovery listener poison-message handling — **would have caught the live
  crash loop**
- Scanner reconnect exhaustion — **would have caught the 959-attempt silence**
- Sweep starvation / query ordering
- `/radar/discovered` at realistic volume (current test data does not exercise
  1.7M rows)
- Page-level and E2E
- Test/dev Redis isolation

### Overall confidence

**Backend logic: very high.** **Backend runtime behaviour under failure:
moderate** — the two things that actually broke are the two things least
covered. **Frontend logic: good. Frontend rendering: low.**

---

## 11. Technical Debt

### Code duplication — low

- `clamp()` in both `radar/normalise.py` and `scoring/normalisers.py` with
  different signatures (radar requires explicit bounds; scoring defaults 0–100).
  Arguably justified, mildly confusing.
- Two watchlist implementations (client-side orphan + backend API).
- Decimal coercion across provider adapters — retained deliberately per the July
  audit.
- Two module conventions (layered vs vertical slice) — coherent but
  undocumented.

### Dead code

- **Frontend: 1,100 lines across 9 modules** (§9)
- **Backend: `app/utils/` — empty package**
- `docker/nginx/nginx.conf` — superseded by Caddy, retained deliberately
- 19 MB of never-scanned indexes

### Architecture issues

| Issue | Location |
| --- | --- |
| API layer writes SQL (6 statements) | `exit_signals/api.py` |
| Private cross-module import | `exit_signals/api.py:36` → `radar/api.py:_days_since` |
| SQL in endpoint | `endpoints/watchlists.py` (1 site) |
| No per-message error isolation | `market/worker.py:165` |
| Unordered `LIMIT` causes livelock | `repositories/score.py:141` |
| No Redis namespace per environment | `core/config.py:155,287` |
| Two module conventions undocumented | repo-wide |

### Performance risks

| Endpoint | Measured | Cause |
| --- | ---: | --- |
| `/radar/discovered` | **3.95s** | Unbounded `count(*)` over a window function on 1.72M rows (1.97s) + outer sort (~2s) |
| `/market/trending` | **2.23s** | `DISTINCT ON` over the full append-only table |
| `/scores/top` | 37ms | Misses two ranking indexes totalling 14 MB |

Plus: stale planner statistics on both large tables; 1.77 GB
`token_score_history` pruned by row-delete rather than partition drop;
`pk_token_market_snapshots` is 70 MB of pure write overhead with zero reads.

### Security concerns

| Item | Assessment |
| --- | --- |
| `DEVELOPMENT_BYPASS_AUTH=true` in local `.env` | Correctly gated — requires `ENVIRONMENT=local`, production raises at import, logged loudly every boot |
| Entire intelligence surface unauthenticated | Deliberate-looking but undocumented; rate limit is the only gate |
| Rate limiter at 42% coverage | Security-relevant code, thinly tested |
| `X-Forwarded-For` honoured only when `TRUSTED_PROXY_IPS` set | Correct — otherwise clients pick their own rate bucket |
| Refresh token: SHA-256 digest only, rotation + reuse detection | Textbook |
| 3 high-severity npm advisories via Next.js | Prior audit found them unreachable; unchanged |
| Trivy in CI | Present |
| Secrets | `SecretStr`, production refuses unsafe config at import |

### Scalability concerns

1. `token_market_snapshots` grows unbounded — 803 MB from ~4 days of a
   **partially working** pipeline. At full discovery rate this is TB-scale
   within months. No partitioning, no retention.
2. Window/`DISTINCT ON` patterns degrade linearly with snapshot count; already
   2–4s.
3. Single Postgres, no read replicas (deliberate, documented).
4. Enrichment scales horizontally by design (`SKIP LOCKED` + lease) — genuinely
   good.
5. Scanner is a singleton by necessity; the 429 wall is a plan limit, not a code
   limit.

---

## 12. Product Roadmap

### M1 — Restore and defend the pipeline

**Objective:** Discovery running again, and structurally incapable of dying
silently.

- Resolve the Helius 429 (plan/quota — a purchasing decision)
- Escalate scanner reconnect from `warning` to `error` past a threshold; add a
  compose healthcheck
- Add `GET /health/pipeline` exposing `max(discovered_at)`, `max(captured_at)`,
  sweep outcomes
- Per-message error isolation in the discovery listener
- Namespace Redis channels by environment

**Complexity:** Low-Medium (2–3 days)
**Files:** `services/scanner/scanner.py`, `services/market/worker.py`,
`core/config.py`, `endpoints/health.py`, `docker-compose.yml`
**Dependencies:** Helius plan
**Risk:** Low — additive, isolated

---

### M2 — Unstarve scoring + reclaim the database

**Objective:** The sweep makes progress; the two big tables stop lying to the
planner.

- Add deterministic ordering + unscorable-token exclusion to
  `mints_without_scores`
- `VACUUM ANALYZE` both large tables; tune autovacuum thresholds
- Drop ~19 MB of never-scanned indexes
- Point `/scores/top` at its existing ranking index

**Complexity:** Low (1–2 days)
**Files:** `repositories/score.py`, one migration, `endpoints/scores.py`
**Dependencies:** M1 preferable
**Risk:** Low — measurable before/after

---

### M3 — Latest-snapshot pointer

**Objective:** One change fixes `/market/trending` (2.23s),
`/radar/discovered` (3.95s), and every future "current state" query.

- `token_latest_snapshot` table maintained on write, or a partial index +
  generated column
- Backfill migration over 1.72M rows
- Repoint both endpoints; cache `/radar/discovered`'s total

**Complexity:** Medium (3–4 days)
**Files:** `models/market.py`, `repositories/market.py`, `radar/repository.py`,
`services/market/service.py`, migration
**Dependencies:** M2 (needs clean stats to verify)
**Risk:** Medium — touches the enrichment write path; needs a benchmark gate

---

### M4 — Ship the Pump.fun Radar

**Objective:** Land the uncommitted work properly.

- Fix the count query (M3 makes this nearly free)
- Composite `(source_program, block_time)` index
- `docs/API.md` + regenerate `openapi.json`
- Frontend surface for discovery candidates
- Decide whether `signals` gets populated now or stays reserved

**Complexity:** Medium (3–5 days)
**Files:** `services/pumpfun_radar.py`, `radar/{api,repository,schemas}.py`,
`docs/`, new frontend page + hook
**Dependencies:** M3
**Risk:** Medium — the admission-vs-scored distinction must survive into the UI,
or it misrepresents unscored candidates as vetted opportunities

---

### M5 — Close the liquidity gap (highest product value)

**Objective:** Make the core signal mean something. Today: avg coverage
44.6/65, avg evidence 40.9, **zero elite tokens ever**, 2 "strong" out of
20,481.

Two routes, per ADR-0002:

- **(a)** Move the composite fill off the enrichment request path into a
  separate backfill worker, or impose a hard per-batch time budget
- **(b)** Derive bonding-curve reserves on-chain via Helius — ADR-0002 names
  this the correct long-term answer

**Complexity:** High (5–8 days)
**Files:** `services/market/providers/composite.py`, `services/market/worker.py`,
possibly a new worker + compose service, `services/helius/client.py` for route
(b)
**Dependencies:** M1 (Helius quota gates route (b))
**Risk:** **High — this exact change already took production down for an hour.**
Requires load testing at real `ENRICHMENT_CONCURRENCY`, not isolated batches of
30. The prior failure was caused precisely by verification that skipped
concurrency.

---

### M6 — Watchlist UI

**Objective:** Give 7 finished endpoints a consumer, and delete the orphan.

- Watchlist page + add/remove from token and radar cards
- Wire `/watchlists/{id}/events`
- Delete `lib/watchlist.ts`
- Raise `endpoints/watchlists.py` coverage from 28%

**Complexity:** Medium (2–3 days)
**Files:** new page + hook, `components/decision/`, `endpoints/watchlists.py`
tests, delete `lib/watchlist.ts`
**Dependencies:** none
**Risk:** Low

---

### M7 — Alerts

**Objective:** Push the event log somewhere. Reads state rather than relying on
event delivery, per the roadmap's own constraint.

**Complexity:** High (5–7 days)
**Files:** new `app/alerts/` module, `events/detector.py`, worker task, settings
UI, migration
**Dependencies:** M6 (watchlists are the natural subscription unit)
**Risk:** Medium — outbound delivery is a new failure surface and a new external
dependency

---

### M8 — Rotation engine

**Objective:** Lead/lag over the stored series (volume leading price, liquidity
leading volume). Roadmap says computable today, and the data confirms it.

**Complexity:** Medium (4–5 days)
**Files:** new `app/rotation/`, radar integration, endpoint, frontend
**Dependencies:** M3
**Risk:** Low — pure read over existing data

---

### M9 — Production hardening

Partition `token_score_history` by month · retention policy for snapshots ·
resolve npm advisories · exercise deploy/rollback for real · decide the auth
posture on the intelligence surface · E2E tests · OpenTelemetry.

**Complexity:** High (1–2 weeks)
**Risk:** Medium

---

### Recommended order

```
M1 → M2 → M3 → M4 → M6 → M5 → M8 → M7 → M9
        (unblock)   (ship)   (value)  (grow)  (harden)
```

M5 has the highest product value but the highest risk and a prior production
failure. M1–M3 are cheap, low-risk, and make M5 measurable — attempting M5
first, on a dead pipeline with stale planner statistics, would repeat the July
incident with less instrumentation.

---

## 13. Version Assessment

### v0.8 — the declared `0.8.0-rc1` is accurate

| | |
| --- | --- |
| **Not v0.1/v0.2** | Far past scaffolding. 20k backend LOC, 12.7k test LOC, 17.5k frontend LOC, 7 migrations, 53 endpoints, 8 services, 2,708 passing tests, two ADRs, a production deployment overlay with backup/deploy/rollback tooling. |
| **Not v0.5** | v0.5 implies core features working but rough edges everywhere. This has 90% backend coverage, mypy clean on 148 files, zero lint findings, zero TODO markers, purity tests enforcing architectural invariants, and a released RC with a documented audit. Discipline is well beyond mid-alpha. |
| **Not v1.0** | Three live pipeline faults with no alerting. The core signal is thin — zero elite tokens have *ever* been produced, and 2 of 20,481 reach "strong". The pump.fun liquidity gap (100% null, 0.20 model weight) is the direct cause and its fix was reverted after taking production down. 7 backend features have no UI. 1,100 lines of dead frontend. No production deployment has ever happened. |
| **Why exactly v0.8** | Every subsystem the roadmap declares complete *is* complete and tested. What separates this from 1.0 is not missing architecture — it is **operational maturity** (nothing watches the watchers) and **signal quality** (the platform is honest that its evidence is thin, which is admirable, but thin evidence is still thin). Both are addressable without redesign. |

**To reach v1.0:** M1 → M2 → M3 → M5 plus one successful production deployment.
Roughly **4–6 weeks**, with M5 carrying most of the risk.

---

## Closing note

The gap between engineering quality and operational health here is unusually
wide. The code is better than most production systems — layer discipline held,
failure modes designed up front rather than retrofitted, an ADR that documents a
self-inflicted outage in full rather than quietly reverting. And it has been
discovering nothing for four days while every container reported healthy.

That is not a contradiction; it is the predictable consequence of investing in
correctness and deferring observability. The cheapest high-value work in this
repository right now is M1 — a healthcheck, a log level, and one endpoint.

---

*Audit performed read-only. No source file was modified. Measurements taken
against the running local stack (`memescope-*` containers) and the repository at
`d38860f` plus uncommitted Pump.fun Radar work.*

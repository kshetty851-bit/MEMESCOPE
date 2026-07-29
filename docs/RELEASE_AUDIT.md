# Release Audit — `v0.8.0-rc1`

Repository, database, API, performance and security audit conducted 29 July
2026 against the running local stack and the rendered production configuration.

**Nothing was deleted.** Every removal candidate is listed with a
recommendation and left in place.

Severity: **S1** breaks production · **S2** degrades materially · **S3** worth
fixing · **S4** cosmetic.

---

## 1. Findings summary

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **S1** | `REDIS_PASSWORD` never reached `scanner`/`enrichment` in production | **Fixed** |
| 2 | **S2** | `/market/trending` takes 5–7 s, degrading linearly | Reported |
| 3 | **S3** | Migration drift blocked `alembic check` as a CI gate | **Fixed** |
| 4 | **S3** | `/scores/top` misses its ranking index (87 ms vs 0.5 ms) | Reported |
| 5 | **S3** | Version reported as `0.1.0` | **Fixed** |
| 6 | **S3** | 30 documented settings never reach containers | Partially fixed |
| 7 | **S3** | 3 high-severity npm advisories, transitively via Next.js | Reported, not reachable |
| 8 | **S4** | OpenAPI understates error responses (401, 404) | Reported |
| 9 | **S4** | `PROJECT_NAME` is "MemeScope AI", branding is MEMESCOPE | Documented, must not change |
| 10 | **S4** | `docker/nginx/nginx.conf` superseded and unused | Retained |
| 11 | **S4** | Duplicate Decimal coercion across two provider adapters | Retained |
| 12 | **S4** | `hooks/use-intelligence.ts` reuses a deliberately-deleted name | Retained |

---

## 2. S1 — `REDIS_PASSWORD` missing from two production services

**The most serious finding, and invisible in development.**

The production overlay starts Redis with
`--requirepass ${REDIS_PASSWORD:?...}`, but the value was supplied to
`backend`, `worker` and `scheduler` as individual service environment entries
rather than through the shared `x-backend-env` anchor. `scanner` and
`enrichment` never received it.

Consequence in production: every Redis call from those two containers fails
with NOAUTH. `scanner.py` publishes discoveries via `core.events`, and the
enrichment worker subscribes with `get_redis().pubsub()` — so the live
discovery pipeline and the WebSocket feed break, while the API looks healthy.
Development, where Redis needs no password, works perfectly.

Verified by rendering the production config before and after:

| Service | Before | After |
|---|---|---|
| backend | ✅ | ✅ |
| worker | ✅ | ✅ |
| scheduler | ✅ | ✅ |
| **scanner** | ❌ | ✅ |
| **enrichment** | ❌ | ✅ |

This is the **third** occurrence of the same trap, after
`FEATURE_AI_SCORING_ENABLED` (§9 of the master context) and `ALLOWED_HOSTS`
(§18, defect 3). The anchor already carried a prose warning both times and it
did not prevent recurrence, so the fix includes
`backend/tests/unit/test_compose_env_contract.py`, which asserts that every
runtime-critical setting lives in the anchor and that `REDIS_PASSWORD` is not
also set per-service. The test was confirmed to fail when the defect is
reintroduced.

---

## 3. S2 — `/market/trending` performance

Measured, warm, local, mean of 5:

| Endpoint | Latency |
|---|---|
| **`/api/v1/market/trending`** | **6,769 ms** |
| `/api/v1/exit-watch` | 78 ms |
| `/api/v1/scores/top?page_size=20` | 53 ms |
| `/api/v1/radar?limit=20` | 15 ms |
| `/api/v1/tokens?page_size=20` | 12 ms |
| `/api/v1/scores/model` | 6 ms |
| `/live`, `/ready` | 5–7 ms |

Query plan: an index scan over `ix_snapshots_mint_captured_desc` reading
**1,550,515 rows** to produce 23,361 distinct mints, hash-joined against 24,196
`discovered_tokens`, then top-N sorted. Execution 5.4–7.1 s depending on cache
state.

The `DISTINCT ON` does ride the index rather than sorting the whole table — the
docstring's claim is correct — but it must still examine every snapshot row
ever written to find the distinct mints. Cost therefore grows linearly with
total snapshots, which accumulate at roughly 1.5M/day.

A bounded `since` does **not** fix it:

| Window | Execution | Tokens returned |
|---|---|---|
| unbounded | 5,359 ms | 23,361 |
| 7 days | **7,999 ms** (worse) | 23,361 |
| 24 hours | 1,884 ms | 20,771 |

**Recommendation.** Maintain a latest-snapshot pointer (a column on
`token_enrichment_state`, or a materialised view) so trending reads ~24k rows
instead of 1.55M. This is a schema and write-path change and was deliberately
not attempted during stabilisation. It is the top post-RC priority.

The frontend polls this endpoint on the feed page
(`/market/trending?sort_by=captured_at&page_size=100`), and the endpoint is
unauthenticated, so it is also the platform's most expensive public surface.
Rate limiting (120/min) bounds but does not neutralise that.

---

## 4. S3 — `/scores/top` does not use its ranking index

`ix_token_scores_ranking_hot` leads with `model_version`, but the default API
request does not constrain it, so the planner falls back to sequential scans.

| Query shape | Plan | Time |
|---|---|---|
| Default (no `model_version`) | Hash join, 2× seq scan, top-N sort | **87.6 ms** |
| With `model_version='v1'` | Index Only Scan | **0.47 ms** |

Confirmed behaviourally: after five real API calls the index's `idx_scan`
counter did not move.

**Recommendation.** Constrain the ranking query to the active
`SCORING_MODEL_VERSION`. No migration required, and it is arguably a
correctness improvement — comparing scores across model versions is
meaningless. Not applied here because it changes which rows can appear in a
ranking, which is a behaviour change rather than a pure optimisation.

---

## 5. S3 — Configuration drift

Cross-checked `Settings` fields against `.env.example` and the compose anchor.

- ✅ **No dead configuration.** Every anchor key is a real setting.
- ✅ **No obsolete `.env.example` entries.** The six non-settings are frontend
  `NEXT_PUBLIC_*` and compose port mappings, correct by design.
- ⚠️ **30 of 64 documented settings are absent from the anchor**, so setting
  them in `.env` silently does nothing.

The most consequential were `REDIS_PASSWORD` (fixed — see §2) and the
`MARKET_SECONDARY_*` group (added). The rest remain and are listed below,
because each is a tuning parameter whose code default is currently correct:

`ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`,
`RATE_LIMIT_ENABLED`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`,
`MARKET_PROVIDER_API_KEY`, `MARKET_PROVIDER_TIMEOUT_SECONDS`,
`MARKET_PROVIDER_MAX_ATTEMPTS`, `MARKET_BREAKER_*` (3),
`ENRICHMENT_CONCURRENCY`, `ENRICHMENT_DEAD_LETTER_THRESHOLD`,
`ENRICHMENT_TIER_*` (7), `SCANNER_*` (5), `HELIUS_RPC_BASE`, `HELIUS_WS_BASE`.

**Recommendation.** Either add them to the anchor or remove them from
`.env.example`. Documenting a knob that does nothing is worse than not
documenting it — `RATE_LIMIT_*` and `MARKET_PROVIDER_API_KEY` are the ones most
likely to be reached for first.

---

## 6. Database audit

**Migrations.** Five revisions, head `0005_radar`. Verified on a scratch
database:

- Fresh install `base → head` — clean.
- Rollback `head → base` — clean, leaving only `alembic_version`, **no orphaned
  tables and no leftover enum types**.
- Re-upgrade — clean.
- `alembic check` — **no drift** after the fix in §1 of the release notes.

**Schema.** Ten tables. Constraints and indexes:

| Table | Indexes | FKs | Uniques | Checks |
|---|---|---|---|---|
| `discovered_tokens` | 11 | 0 | 0 | 0 |
| `token_scores` | 8 | 1 | 1 | 6 |
| `radar_tokens` | 6 | 1 | 1 | 0 |
| `refresh_tokens` | 5 | 2 | 0 | 0 |
| `token_enrichment_state` | 5 | 1 | 1 | 0 |
| `token_market_snapshots` | 4 | 1 | 0 | 0 |
| `radar_achievements` | 4 | 1 | 1 | 0 |
| `token_score_history` | 3 | 1 | 0 | 6 |
| `radar_snapshots` | 3 | 1 | 0 | 0 |
| `users` | 3 | 0 | 0 | 0 |

**Storage** (live database, 30 h uptime):

| Table | Total | Indexes | Rows |
|---|---|---|---|
| `token_score_history` | 1,093 MB | 95 MB | 637,921 |
| `token_market_snapshots` | 721 MB | 323 MB | 1,545,347 |
| everything else | < 25 MB each | | |

`token_score_history` averages ~1.7 KB/row, driven by the component JSONB — as
designed. Materiality is working: over three hours, 83% of writes were
heartbeats at 1.5–3.4 rows per token per hour, well under the 300 s ceiling.
Daily thinning beyond 30 days exists but has not yet triggered, so **plan
capacity for roughly 1 GB/day of history growth** until it does.

**Unused indexes.** Statistics were never reset and are demonstrably live
(3.1M scans on the busiest index), so the following genuinely saw zero scans in
30 hours: both `token_scores` ranking indexes, and six on `discovered_tokens`
(~7 MB total).

**Recommendation: keep all of them.** They are unused because these tables are
small enough (20–24k rows) that the planner prefers sequential scans; they are
insurance that engages as data grows, and the ranking index demonstrably
delivers a 52× improvement when the query shape matches. Re-evaluate at 10×
volume.

---

## 7. API audit

33 paths / 34 operations. Spec generated to
[`docs/api/openapi.json`](api/openapi.json).

**Verified correct**

- Error envelope is uniform: `{error: {code, message, details}, request_id}`.
- Decimals serialise as strings throughout.
- Absence is state, not error: unscored tokens return 200 with `score: null`
  and a `status`; only an undiscovered mint is 404.
- Filters are echoed with `applied_filters`, `total` and `candidate_total`.
- 401 on bad credentials, 422 on malformed input, 429 with `Retry-After`,
  `X-RateLimit-Limit` and `X-RateLimit-Remaining`.

**Gaps (S4).** The spec understates error responses. `/tokens/{mint}`,
`/radar/{mint}` and `/exit-watch/{mint}` return 404 but document only 200/422;
auth endpoints return 401 but do not document it. Documentation-only, no
behaviour change required.

**Worth confirming.** `/smart-money/{mint}` returns **200** for a mint that does
not exist, where its siblings return 404. This is arguably correct — "wallets
cannot be seen" does not depend on the mint existing — but it is an
inconsistency that should be intentional rather than incidental.

---

## 8. Security review

| Check | Result |
|---|---|
| Secrets in git history | ✅ None. All `.env*` variants ignored. |
| Secrets in tracked files | ✅ Only a labelled test key in `pyproject.toml` |
| SQL injection surface | ✅ None. ORM throughout; every `text()` is a static index expression or server default with no user input. |
| Rate limiting | ✅ Exactly 120 pass, then 429 with `Retry-After`. Health probes deliberately exempt. |
| Security headers | ✅ `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, CSP `default-src 'none'` |
| HSTS | ✅ Production only, via Caddy |
| Container user | ✅ Production stages run non-root (`memescope`, `nextjs`). Development stages run as root — dev-only, expected. |
| JWT | ✅ Issuer validated on decode; refresh cookie `HttpOnly; Secure; SameSite=lax` |
| Production hardening | ✅ Boot fails on auth bypass, insecure cookies, or missing `ALLOWED_HOSTS`/`CORS_ORIGINS` |
| Python dependencies | ✅ Application dependencies clean (`pip` itself is outdated in the image — build tooling, not runtime) |
| npm dependencies | ⚠️ 3 high severity, transitive via Next.js |

**On the npm advisories.** `sharp` (libvips CVEs) and `postcss` arrive through
`next@15.5.22`. `next/image` is **not used anywhere in the application**, so the
`sharp` path is not reachable. `npm audit fix --force` resolves them by
installing `next@9.3.3` — a catastrophic downgrade, not a fix. Correct action:
leave in place, monitor for a patched Next.js 15.x.

**Not a finding.** `GET /users/me` returns 200 unauthenticated *in local
development only*, because `DEVELOPMENT_BYPASS_AUTH=true`. Production refuses to
boot with that flag set, and `test_auth_bypass.py` locks the behaviour.

---

## 9. Code quality

- **Zero** TODO / FIXME / XXX / HACK markers in `backend/app` or `frontend/src`.
- No commented-out code blocks.
- No circular imports (the application boots and mypy strict passes across 126
  modules).
- Largest function is 136 lines (`MarketEnrichmentService.enrich`), a documented
  orchestration path. Next are `score_mints` (121) and the two Radar `evaluate`
  functions (105, 100). None pathological; `enrich` is the reasonable
  decomposition candidate.
- Largest module is 529 lines (`repositories/score.py`).

**Retained removal candidates**

| Item | Why retained |
|---|---|
| `docker/nginx/nginx.conf` | Superseded by Caddy and unreferenced. Harmless; deleting is safe whenever someone wants to. |
| `_decimal` / `_reserve` duplication across the two provider adapters | Near-duplicate JSON coercion helpers. They differ (one rejects negatives), and ADR 0001 makes adapters own their quirks. Extracting a shared helper is reasonable but is churn on tested code during stabilisation. |
| `hooks/use-intelligence.ts`, `types/intelligence.ts` | Reuse the name of the deliberately-deleted `lib/intelligence.ts`. **Verified clean** — pure Exit Watch API bindings with no client-side verdicts. Renaming to `exit-signals` would remove a genuine confusion trap. |

**`PROJECT_NAME` must not be renamed casually.** It reads "MemeScope AI" while
the product brands as MEMESCOPE, and it is tempting to align. It is the JWT
`iss` claim, validated on every decode — changing it signs out every user. A
comment now says so at the definition.

---

## 10. Verification status

All gates green at the time of tagging.

| Gate | Result |
|---|---|
| Backend tests | **2,433 passed**, 15 skipped |
| Backend coverage | 90% |
| ruff / ruff-format | Pass (186 files) |
| mypy strict | Pass (126 modules) |
| `alembic check` | No drift |
| Frontend tests | **113 passed** (12 files) |
| eslint / tsc | Pass |
| Frontend production build | Succeeds — 102 kB shared First Load JS, pages 123–151 kB |
| Migration round trip | Fresh install, rollback, re-upgrade all clean |

The 15 skips are `test_compose_env_contract.py`, which needs the repository root
and therefore skips inside the backend container while running normally in CI
(which runs pytest from `backend/` on the runner). Verified to pass — and to
fail correctly against a reintroduced defect — by staging the compose files
where the container could reach them.

**Not measured.** Real FPS (the agent harness renders headless, which pauses
`requestAnimationFrame`, so any number would be fiction); behaviour under
concurrent load; Caddy's ACME path; Sentry event delivery.

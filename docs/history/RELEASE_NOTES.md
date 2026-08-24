# MEMESCOPE `v0.8.0-rc1`

**Release candidate for private alpha.** 29 July 2026.

First tagged release. Everything from the AI scoring engine onwards had been
built but never committed — 148 files across ten phases lived only in a working
tree. This release commits that work as reviewable history, audits it, fixes
what the audit found, and versions it.

No new product features were added. Two production defects were fixed, and
several were found and deliberately left for after the RC.

---

## Major features

| Area | What it does |
|---|---|
| **AI Scoring Engine** | Deterministic weighted model over six live signals. No ML, no LLM in the scoring path. Score, evidence, coverage, grade, component waterfall and history. Weights published at `/api/v1/scores/model`. |
| **Opportunity Radar** | Tracks projects of any age, asking which are getting *stronger*. Market cap is never a qualification. Permanent, append-only track record. |
| **Exit Watch** | Seven checkable deterioration signals, assessed live from the stored series. Never a sell signal. |
| **Hall of Fame / Lessons** | One table ordered two ways — best calls by peak, failed calls by current — behind one toggle on one page. |
| **Composite market provider** | Fills the pump.fun bonding-curve liquidity gap that caps ~90% of the feed at 45% coverage. Opt-in. |
| **Observatory frontend** | Landing page, Command Center, Radar, Exit Watch, track record, About, alpha surfaces. Zero JavaScript per frame in the scene. |
| **Production overlay** | Caddy edge with automatic TLS, tiered backups, deploy/rollback/health-check scripts, Sentry. |

## Architecture

`router → service → repository → database`, enforced by convention and tests.
No business logic in routers, no HTTP in services, no external calls in
repositories.

Two engines (`services/scoring`, `app/radar`) are **pure**: no database,
network, clock or randomness, with time entering as an explicit `now`. A test
parses every module's AST and fails the build on an I/O import. That purity is
what lets a token page recompute a score rather than trust a cached one, which
is what makes the track record an audit rather than a claim.

Enrichment commits snapshots in one transaction and scores in another.
Snapshots are the durable asset; a scoring failure must never cost one.

## Breaking changes

- **`lib/intelligence.ts` deleted** (frontend). 246 lines of client-side scoring
  that could disagree with the engine about the same token. All scoring now
  comes from the backend. No API contract changed; this is internal to the
  frontend.
- **`REDIS_PASSWORD` moved to the `x-backend-env` anchor** and removed from
  three per-service blocks. No action needed — the variable name and semantics
  are unchanged — but a deployment that overrode it per-service should verify
  the rendered config.

No API route changed shape. Every endpoint added since the last state was
additive.

## Migration notes

Migration head is **`0005_radar`**. From an existing deployment:

```bash
./scripts/deploy.sh
```

which backs up, migrates, restarts and verifies, rolling back on failure.

Verified for this release:

- **Fresh install** — `base → head` applies cleanly.
- **Rollback** — `head → base` leaves only `alembic_version`, with no orphaned
  tables or enum types.
- **Re-upgrade** — clean.
- **No drift** — `alembic check` reports no new operations, and is now a CI gate.

Rollback does not reverse migrations; they are forward-only, so the pre-deploy
backup is the recovery path for a bad schema change.

## Fixed in this release

**`REDIS_PASSWORD` never reached the scanner or enrichment workers.** Production
starts Redis with `--requirepass`, but the password was set on `backend`,
`worker` and `scheduler` individually rather than in the shared anchor. The
scanner would have failed to publish discoveries and the enrichment listener
would have failed to subscribe — the live pipeline, broken in production and
working perfectly in development. This was the **third** occurrence of the same
trap, so `test_compose_env_contract.py` now asserts the contract and was
confirmed to fail when the defect is reintroduced.

**Migration drift blocked `alembic check`.** `ix_refresh_tokens_expires_at`
existed in the database but not in the model, so drift was reported
permanently. Reconciled by declaring the index; no schema change. `alembic
check` is now a CI gate.

**Version reported as `0.1.0`.** Bumped across `config.py`, `pyproject.toml`,
`package.json` and the frontend env default.

## Known limitations

Nothing here is hidden in the product either.

**Data that does not exist**

- Four of nine scoring signals — contract safety, holder distribution, smart
  money, narrative — have no data source. They are declared, weighted and
  charged to coverage. Available weight is 0.65 and the Elite gate needs 70, so
  **no token can be certified Elite in v1**. Gold stays dark. Intended.
- Confidence reads 30–45% across the feed. That is the coverage mechanism
  working, not a fault.
- Smart money returns every field as `null` (never zero) with an
  `unavailable_reason`. Exit Watch coverage caps at 78% (7 of 9 signals).
- The Radar's `community` dimension and its `strong_community` category are
  declared unreachable, with `reachable: false` and a reason on the API.

**Performance**

- **`/market/trending` takes ~5–7 s** and degrades linearly as snapshots
  accumulate (~1.5M/day). It walks 1,550,515 index rows to produce 23,361
  distinct mints. A bounded `since` does not fix it — a 7-day window measured
  *slower* than unbounded. The real fix is a latest-snapshot pointer, which is
  architectural and was deliberately not attempted during stabilisation. **This
  is the top post-RC priority.**
- `/scores/top` runs ~40–90 ms because the default request does not constrain
  `model_version`, the leading column of `ix_token_scores_ranking_hot`. Supplying
  it drops the query from 87 ms to 0.5 ms. Not changed here because it alters
  which rows can appear in a ranking.
- `token_score_history` is 1 GB at 638k rows. Thinning beyond 30 days exists but
  has not yet triggered.

**Operational**

- **Never deployed to a real host.** Everything is verified locally and in a
  production-mode rehearsal. Caddy's ACME path, real DNS and behaviour under
  load remain unproven.
- No zero-downtime deploy; expect seconds of downtime.
- Backups sit on the same host as the database they protect.
- No log aggregation beyond `docker compose logs`.
- Offset pagination on `/scores/top` can shift a row between pages.
- 3 high-severity npm advisories, all transitive through Next.js
  (`sharp`/`libvips`, `postcss`). **Not reachable** — `next/image` is unused —
  and `npm audit fix --force` would downgrade Next.js to 9.3.3. Monitoring for a
  patched 15.x.
- The OpenAPI spec understates error responses: 401 on auth endpoints and 404 on
  several `{mint}` endpoints are returned but undocumented.

## Future roadmap

**Buildable now, no new data needed**

1. `/market/trending` latest-snapshot pointer.
2. Rotation engine — volume leading price, liquidity leading volume.
3. On-chain bonding-curve reserves via Helius, closing the liquidity gap
   completely rather than partially.

**Blocked until a data pipeline exists** — and deliberately not estimated in the
meantime: smart wallet intelligence, rug detection (which *unlocks Elite*),
narrative intelligence, alerts, portfolio.

---

*Full technical detail: [`MEMESCOPE_MASTER_CONTEXT.md`](MEMESCOPE_MASTER_CONTEXT.md).
Audit findings: [`docs/RELEASE_AUDIT.md`](docs/RELEASE_AUDIT.md). Operator
guidance: [`ALPHA_CHECKLIST.md`](ALPHA_CHECKLIST.md).*

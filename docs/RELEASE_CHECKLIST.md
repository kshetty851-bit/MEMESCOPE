# Release Checklist — `v0.8.0-rc1`

Status at tagging. ✅ verified · ⬜ outstanding · ➖ not applicable yet.

Anything marked ⬜ is **not** a silent gap: each says what blocks it.

---

## Code and version

- ✅ All work committed — 148 files across 18 logical commits
- ✅ Conventional Commits throughout, breaking change marked `!`
- ✅ Version consistent across `config.py`, `pyproject.toml`, `package.json`,
      frontend env default, and the live `/live` response
- ✅ Zero TODO/FIXME markers
- ✅ Tagged `v0.8.0-rc1`

## Backend

- ✅ 2,433 tests passing, 90% coverage (100% on every scoring module)
- ✅ ruff, ruff-format clean (186 files)
- ✅ mypy strict clean (126 modules)
- ✅ Purity tests enforce no I/O in scoring and Radar engines
- ✅ Error envelope uniform across every endpoint
- ✅ Decimals as strings on the wire, `NUMERIC` in Postgres, never float

## Frontend

- ✅ 113 tests passing (12 files)
- ✅ eslint (`--max-warnings=0`) and tsc clean
- ✅ Production build succeeds — 102 kB shared First Load JS
- ✅ Loading / empty / error states distinct on the Command Center
- ✅ Dashboard issues 5 requests, zero duplicates (test-enforced)
- ✅ No client-side scoring — `lib/intelligence.ts` deleted
- ✅ Reduced-motion honoured; zero JavaScript per frame in the scene
- ⬜ Real FPS measurement — needs a visible browser; the harness renders
      headless, which pauses `requestAnimationFrame`
- ⬜ Accessibility sweep beyond keyboard/focus basics

## Database

- ✅ Fresh install `base → head`
- ✅ Rollback `head → base` — no orphaned tables or enum types
- ✅ Re-upgrade clean
- ✅ `alembic check` reports no drift, and is now a CI gate
- ✅ Ten tables, constraints and indexes inventoried
- ⬜ `token_score_history` capacity plan — ~1 GB/day until 30-day thinning
      engages

## Configuration

- ✅ No dead configuration in the compose anchor
- ✅ No obsolete `.env.example` entries
- ✅ `REDIS_PASSWORD` reaches all five application services (**was broken**)
- ✅ Contract test prevents a fourth recurrence of the anchor trap
- ⬜ 28 documented settings still absent from the anchor — see audit §5

## Docker

- ✅ Production images run non-root (`memescope`, `nextjs`)
- ✅ Healthchecks on both images
- ✅ Only 80/443 published in production (`!reset []`, verified in rehearsal)
- ✅ Multi-stage builds; dev and prod targets separate

## Security

- ✅ No secrets in git history; all `.env*` ignored
- ✅ No SQL injection surface — ORM throughout
- ✅ Rate limiting verified live: 120 pass, then 429 with `Retry-After`
- ✅ Security headers present; HSTS production-only
- ✅ Production refuses to boot with auth bypass, insecure cookies, or missing
      `ALLOWED_HOSTS`/`CORS_ORIGINS`
- ✅ Python application dependencies clean
- ⬜ 3 high-severity npm advisories — transitive via Next.js, **not reachable**
      (`next/image` unused); `audit fix --force` would downgrade to Next 9

## Performance

- ✅ API latency measured across all 16 public surfaces
- ✅ Query plans captured for the two hot paths
- ⬜ **`/market/trending` at 5–7 s** — top post-RC priority, fix is architectural
- ⬜ `/scores/top` ranking index unused by default (87 ms vs 0.5 ms)
- ⬜ Load testing — never run

## Monitoring and logging

- ✅ `/live` and `/ready`, with database and Redis reported individually
- ✅ Structured JSON logs with a request id on every line
- ✅ Sentry initialises when a DSN is set (empty is supported, not broken)
- ⬜ Sentry receiving a real event — no DSN available
- ⬜ Log aggregation — stdout only

## Backups and recovery

- ✅ `pg_dump -Fc` produces a valid dump (380 MB, TOC readable)
- ✅ **Restore round trip verified** — exact row parity, correct migration head
- ✅ Backup tiers 7 daily / 4 weekly / 6 monthly, hard-linked
- ✅ Interrupted dumps cannot be mistaken for restorable ones
- ✅ `restore.sh` refuses to run unattended
- ✅ `deploy.sh` backs up before building, rolls back on failed health check
- ⬜ Off-site backups — dumps sit on the same host as the database

## Documentation

- ✅ `MEMESCOPE_MASTER_CONTEXT.md` current (table count, path count, RC section)
- ✅ `README.md`, `ARCHITECTURE.md`, `ROADMAP.md` refreshed — all three had
      described AI scoring as unimplemented
- ✅ `RELEASE_NOTES.md`, `docs/RELEASE_AUDIT.md`, this checklist
- ✅ `ALPHA_CHECKLIST.md` for operators
- ✅ OpenAPI snapshot committed at `docs/api/openapi.json`
- ✅ ADR 0002 for the composite provider decision
- ⬜ OpenAPI understates 401/404 responses

## Deployment

- ✅ Production overlay validates and renders
- ✅ Deploy, rollback, health-check and backup scripts present
- ✅ Production-mode rehearsal passed (Phase 6C, six defects found and fixed)
- ⬜ **Never deployed to a real host** — no server, domain or credentials
- ⬜ Caddy ACME path unproven (rehearsal used the internal CA)
- ⬜ Zero-downtime deploy — `up -d` restarts containers

## Cloudflare

- ✅ Tunnel working (per handoff)
- ⬜ Not exercised in this audit — no public deployment to verify against

---

## Go / no-go for private alpha

**Go**, for an invited cohort of 10–25, with two caveats to communicate:

1. **`/market/trending` is slow and gets slower.** It backs the feed page. If
   the alpha runs more than a few days, fix it first.
2. **The first real deploy will still be the first real deploy.** Everything is
   verified locally and in rehearsal; DNS, ACME and real latency are not.

**Before inviting anyone:** configure `NEXT_PUBLIC_FEEDBACK_ENDPOINT` or
`NEXT_PUBLIC_FEEDBACK_URL`. Without one, reports are shown back for copying and
nothing is collected.

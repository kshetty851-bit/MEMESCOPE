# Deployment

## Overview

The production stack is the local stack with a different overlay: production
build targets, no source mounts, no published database or cache ports, resource
limits, and nginx terminating TLS.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

or `make prod-up`.

## Required configuration

Production refuses to boot without these. That is intentional — a misconfigured
process should fail loudly at startup, not serve traffic insecurely.

| Variable               | Requirement                                     |
| ---------------------- | ----------------------------------------------- |
| `ENVIRONMENT`          | `production`                                     |
| `DEBUG`                | must be `false`                                  |
| `SECRET_KEY`           | ≥ 32 chars, unique per environment               |
| `ALLOWED_HOSTS`        | explicit list — wildcard is rejected             |
| `CORS_ORIGINS`         | explicit list of frontend origins                |
| `REFRESH_COOKIE_SECURE`| must be `true`                                   |
| `POSTGRES_PASSWORD`    | strong, from a secret manager                    |
| `REDIS_PASSWORD`       | required — Redis holds sessions                  |
| `NEXT_PUBLIC_API_URL`  | public API URL (inlined at frontend build time)  |

Generate a secret:

```bash
openssl rand -base64 48
```

Secrets belong in your platform's secret store (AWS Secrets Manager, GCP Secret
Manager, Docker/Kubernetes secrets) — never in the repository, never in an
image layer.

## Images

Both Dockerfiles are multi-stage and run as a non-root user (uid 1001).

- Backend: `python:3.12-slim`, dependencies resolved with `uv`, gunicorn
  supervising uvicorn workers.
- Frontend: `node:22-alpine`, Next.js `standalone` output so the runtime image
  contains only what the server needs.

Note that `NEXT_PUBLIC_*` values are baked in at build time. Pointing the
frontend at a different API means a rebuild, not a restart.

## Migrations

`scripts/entrypoint.sh` runs `alembic upgrade head` before starting the server,
gated by `RUN_MIGRATIONS` (workers set it to `false` so only one process
migrates).

For zero-downtime releases, run migrations as a separate step before rolling
pods, and keep each migration backward-compatible with the currently deployed
code:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm backend alembic upgrade head
```

Expand/contract for a rename: add the new column, backfill, deploy code writing
both, deploy code reading the new one, then drop the old column in a later
release. Never rename in one shot.

## Health checks and rollout

- Liveness: `GET /live` — restart the container only if this fails.
- Readiness: `GET /ready` — remove from the load balancer when this fails.

Do not point liveness at `/ready`. A brief database blip would otherwise
restart every container at once and turn a small outage into a large one.

## Scaling

- **Backend** is stateless; scale horizontally. Workers per container ≈
  `2 × CPU + 1`; the default of 4 suits a 2-vCPU instance.
- **Workers** scale by queue depth, independently of the API.
- **Scheduler (Beat)** must run as exactly one replica. Two schedulers means
  every periodic job fires twice.
- **Postgres** scales up first, then out via read replicas. The async engine and
  repository layer keep that change local.

## Backups

```bash
docker compose exec -T postgres pg_dump -U memescope -Fc memescope > backup.dump
docker compose exec -T postgres pg_restore -U memescope -d memescope -c < backup.dump
```

Automate daily, retain 30 days, and store off-host. A backup that has never been
restored is not a backup — test the restore path on a schedule.

Redis holds only regenerable state (rate counters, denylist, task queue). Losing
it logs nobody out; it just clears the denylist early.

## Database maintenance

Autovacuum handles this in normal operation, and migration `0007_maintenance`
tunes it per-table so it keeps up with the two append-only tables that grow
continuously. Nothing below runs automatically — deliberately. `VACUUM` on
`token_score_history` rewrites ~1.8 GB, and a scheduled job that decides to do
that on its own during a launch burst is a worse outage than the drift it fixes.

**Check before you act.** This is read-only and answers whether maintenance is
worth its cost:

```bash
make db-stats
```

It reports `pg_class.reltuples` — the number the planner actually reads —
against the true row count. A `drift_factor` near 1.0 means the planner's
estimates are sound and there is nothing to fix. Do not use
`pg_stat_user_tables.n_live_tup` for this: it is a separate activity counter
that is discarded on an unclean shutdown, and reading it reports enormous drift
the planner never saw.

**Refresh statistics.** Seconds, no table rewrite, no lock that blocks reads or
writes. Safe to run on a live system at any time:

```bash
make db-analyze
```

**Reclaim space.** Minutes, rewrites the table. Run it deliberately, during a
quiet period, and only when dead tuples have actually accumulated — on
append-only tables like `token_market_snapshots` that is rare:

```bash
make db-vacuum
```

Both wrap `python -m app.db.maintenance`, which takes `--table` (repeatable) to
scope the work and runs each statement separately so a failure names the table
it failed on.

When to run `db-analyze` by hand:

- after a restore, a bulk import, or a large `DELETE`
- after `make migrate` adds an index to a large table
- when a query's plan changes for no apparent reason and `make db-stats` shows
  a drift factor materially away from 1.0

## TLS

Place certificates at `docker/nginx/certs/fullchain.pem` and `privkey.pem`
(gitignored). The nginx config redirects HTTP to HTTPS and leaves
`/.well-known/acme-challenge/` open for Let's Encrypt renewals.

## Observability

Logs are JSON on stdout — ship them with whatever the platform provides
(CloudWatch, Loki, Datadog). Useful fields: `request_id`, `status_code`,
`duration_ms`, `user_id`, `event`.

Set `SENTRY_DSN` to enable error reporting.

Worth alerting on: `/ready` failing on more than one instance, p95
`duration_ms`, 5xx rate, `refresh_token_reuse_detected` (possible token theft),
and Celery queue depth.

## Deployment checklist

- [ ] Secrets set in the platform secret store, not in the repo
- [ ] `ENVIRONMENT=production`, `DEBUG=false`
- [ ] `ALLOWED_HOSTS` and `CORS_ORIGINS` set explicitly
- [ ] TLS certificates in place and renewal tested
- [ ] Migrations applied and reversible
- [ ] Backups scheduled, and a restore tested at least once
- [ ] Exactly one Beat scheduler replica
- [ ] Health checks wired to the load balancer
- [ ] Log shipping and alerting confirmed working
- [ ] `/docs` returns 404 (auto-disabled in production)

# MemeScope AI

AI-powered Solana meme coin discovery platform.

**Status: `v0.8.0-rc1` — release candidate for private alpha.**

The platform foundation (auth, API, database, cache, workers, CI), the Solana
discovery engine, market enrichment, the deterministic AI scoring engine, the
Opportunity Radar with its permanent track record, Exit Watch, and the
production deployment overlay are all in place and verified.

Four of nine scoring signals have no data source and are declared unavailable
rather than estimated, so **no token can be certified Elite in v1**. That is the
intended outcome, not a defect — see [Known limitations](#known-limitations).

The single source of truth is
[`MEMESCOPE_MASTER_CONTEXT.md`](MEMESCOPE_MASTER_CONTEXT.md); release specifics
are in [`RELEASE_NOTES.md`](RELEASE_NOTES.md).

---

## Stack

| Layer      | Choice                                        |
| ---------- | --------------------------------------------- |
| Backend    | FastAPI · Python 3.12 · SQLAlchemy 2 (async)   |
| Database   | PostgreSQL 16 · Alembic migrations             |
| Cache      | Redis 7 (sessions, rate limits, denylist, bus) |
| Workers    | Celery + Beat                                  |
| Chain data | Helius (Solana) · DexScreener + GeckoTerminal   |
| Frontend   | Next.js 15 (App Router) · React 19 · TS 5      |
| Styling    | Tailwind CSS v4                                |
| State      | Zustand (session) · TanStack Query (server)    |
| Runtime    | Docker Compose · Caddy in production            |
| CI         | GitHub Actions — lint, types, tests, images    |

## Quick start

```bash
make init
```

Then:

```bash
make up
```

| Service      | URL                          |
| ------------ | ---------------------------- |
| Frontend     | http://localhost:3000        |
| API docs     | http://localhost:8001/docs   |
| Readiness    | http://localhost:8001/ready  |

> **Host ports are deliberately shifted** to avoid colliding with another local
> project, and this is the most common source of confusion: the API is on
> **8001** (not 8000), Postgres on **5433**, Redis on **6380**.

The stack also runs four background processes alongside `backend` and
`frontend`: `worker` and `scheduler` (Celery), `scanner` (Helius discovery), and
`enrichment` (DexScreener refresh loop). The last two only do work when their
feature flags are on — see below.

Apply migrations and create a local admin:

```bash
make migrate && make seed
```

`make help` lists every target.

## Repository layout

```
MEMESCOPE/
├── backend/            FastAPI service — see backend/README.md
│   ├── app/            api · core · db · models · repositories · schemas
│   │                   services · middleware · workers
│   │   └── services/   auth · user · token · helius · scanner · market
│   ├── alembic/        Database migrations
│   └── tests/          unit (fast) + integration (real Postgres/Redis)
├── frontend/           Next.js app
│   └── src/            app · components · hooks · lib · stores · styles · types
├── docker/             Postgres init SQL, Caddy config
├── docs/               Architecture, API, development, deployment
├── .github/workflows/  CI pipeline
├── docker-compose.yml       Local stack
├── docker-compose.prod.yml  Production overlay
└── Makefile            Developer entrypoint
```

## Architecture in one paragraph

Requests enter through middleware that assigns a request id, applies rate
limits, and sets security headers. Routers in `app/api/v1` handle HTTP concerns
only and delegate to services, which hold business rules and know nothing about
FastAPI. Services use repositories for all database access. Errors are raised as
`AppError` subclasses and rendered into a single JSON envelope, so every failure
looks the same to clients. Anything slower than a request goes to Celery.

Discovery and enrichment run outside the request path. The scanner subscribes to
Helius, parses new mints, persists them, and publishes each discovery to a Redis
channel; every API process bridges that channel to its own WebSocket clients, so
the live feed works across N gunicorn workers. Enrichment polls DexScreener on
an age-tiered schedule — minutes-old tokens every 30s, week-old tokens every few
hours — behind a circuit breaker, writing snapshots that back token history and
the trending endpoint.

Full detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — layers, data model, decisions
- [Development](docs/DEVELOPMENT.md) — daily workflow, conventions, testing
- [API](docs/API.md) — endpoints, auth flow, error format
- [Deployment](docs/DEPLOYMENT.md) — production setup and operations

## What lives where

| Feature                  | Implemented in                                       |
| ------------------------ | ---------------------------------------------------- |
| Solana scanning          | `backend/app/services/scanner/` · `services/helius/`  |
| Token models             | `backend/app/models/token.py` · `models/market.py`    |
| Market enrichment        | `backend/app/services/market/`                        |
| Market providers         | `backend/app/services/market/providers/`              |
| AI scoring engine        | `backend/app/services/scoring/`                       |
| Opportunity Radar        | `backend/app/radar/`                                  |
| Exit Watch / smart money | `backend/app/exit_signals/`                           |
| Discovery API + feed     | `backend/app/api/v1/endpoints/tokens.py`              |
| Observatory UI           | `frontend/src/app/(dashboard)/`                       |

Feature flags live in `app/core/config.py`, all defaulting to off:
`FEATURE_SCANNER_ENABLED` (requires `HELIUS_API_KEY`),
`FEATURE_ENRICHMENT_ENABLED`, `FEATURE_AI_SCORING_ENABLED` (requires
enrichment) and `FEATURE_RADAR_ENABLED`.

> ⚠️ **Any new setting must also be added to the `x-backend-env` anchor in
> `docker-compose.yml`.** A setting absent from that anchor never reaches the
> containers and silently falls back to its code default regardless of `.env`.
> This has happened three times; `backend/tests/unit/test_compose_env_contract.py`
> now asserts it for runtime-critical settings.

## Known limitations

Stated up front because the product states them too — see
[`ALPHA_CHECKLIST.md`](ALPHA_CHECKLIST.md) for the full operator list.

- **Four of nine scoring signals have no data source.** Contract safety, holder
  distribution, smart money and narrative are declared, weighted and charged to
  coverage. Available weight totals 0.65 and the Elite gate needs 70, so **no
  token can be certified Elite**.
- **Confidence reads low across the whole feed** (typically 30–45%). That is the
  coverage mechanism working, not a fault.
- **Liquidity is missing for pump.fun bonding-curve pools** from DexScreener.
  `MARKET_PROVIDER=composite` fills part of this gap; the fill is budget-limited
  and covers a fraction of peak demand.
- **`/market/trending` is slow** (~5–7s) and degrades as snapshots accumulate.
  See `RELEASE_NOTES.md` for the measurement and the planned fix.
- **Smart money is unavailable by construction**, not by absence of activity.
- Read-only: no watchlist, alerts or portfolio. No wallet connection; nothing is
  ever signed.
- Scores are **not predictions**. The model reads current state.

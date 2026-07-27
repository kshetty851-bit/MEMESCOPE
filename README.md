# MemeScope AI

AI-powered Solana meme coin discovery platform.

**Status: Days 1–3 complete, plus the frontend Observatory.** The platform
foundation (auth, API, database, cache, workers, CI), the Solana discovery
engine (Helius scanner, live WebSocket stream, token storage, REST feed), and
market enrichment (DexScreener provider, adaptive refresh scheduling, historical
snapshots, trending) are all in place. AI scoring is the next milestone and is
deliberately *not* implemented yet; the architecture leaves a clearly marked
seam for it.

---

## Stack

| Layer      | Choice                                        |
| ---------- | --------------------------------------------- |
| Backend    | FastAPI · Python 3.12 · SQLAlchemy 2 (async)   |
| Database   | PostgreSQL 16 · Alembic migrations             |
| Cache      | Redis 7 (sessions, rate limits, denylist, bus) |
| Workers    | Celery + Beat                                  |
| Chain data | Helius (Solana) · DexScreener (market)         |
| Frontend   | Next.js 15 (App Router) · React 19 · TS 5      |
| Styling    | Tailwind CSS v4                                |
| State      | Zustand (session) · TanStack Query (server)    |
| Runtime    | Docker Compose · nginx in production           |
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
| API docs     | http://localhost:8000/docs   |
| Readiness    | http://localhost:8000/ready  |

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
├── docker/             Postgres init SQL, nginx config
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

| Feature              | Implemented in                                      |
| -------------------- | --------------------------------------------------- |
| Solana scanning      | `backend/app/services/scanner/` · `services/helius/` |
| Token models         | `backend/app/models/token.py` · `models/market.py`   |
| Market enrichment    | `backend/app/services/market/`                       |
| Discovery API + feed | `backend/app/api/v1/endpoints/tokens.py`             |
| Market API           | `backend/app/api/v1/endpoints/market.py`             |
| Observatory UI       | `frontend/src/app/(dashboard)/`                      |

## Where the next features go

| Feature              | Lands in                                            |
| -------------------- | --------------------------------------------------- |
| AI scoring           | `backend/app/services/scoring/`                      |
| Score API            | `backend/app/api/v1/endpoints/` + a router line      |
| Score models         | `backend/app/models/` + a migration                  |

Three feature flags live in `app/core/config.py`, all defaulting to off:
`FEATURE_SCANNER_ENABLED` (requires `HELIUS_API_KEY`),
`FEATURE_ENRICHMENT_ENABLED`, and `FEATURE_AI_SCORING_ENABLED` — the seam for
the next milestone.

# MemeScope AI

AI-powered Solana meme coin discovery platform.

**Status: Day 1 — platform foundation.** Authentication, API, database, cache,
background workers, and CI are in place. Blockchain scanning, token analytics,
and AI scoring are deliberately *not* implemented yet; the architecture leaves
clearly marked seams for them.

---

## Stack

| Layer      | Choice                                        |
| ---------- | --------------------------------------------- |
| Backend    | FastAPI · Python 3.12 · SQLAlchemy 2 (async)   |
| Database   | PostgreSQL 16 · Alembic migrations             |
| Cache      | Redis 7 (sessions, rate limiting, denylist)    |
| Workers    | Celery + Beat                                  |
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
│   ├── alembic/        Database migrations
│   └── tests/          unit (fast) + integration (real Postgres/Redis)
├── frontend/           Next.js app
│   └── src/            app · components · hooks · lib · stores · types
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

Full detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — layers, data model, decisions
- [Development](docs/DEVELOPMENT.md) — daily workflow, conventions, testing
- [API](docs/API.md) — endpoints, auth flow, error format
- [Deployment](docs/DEPLOYMENT.md) — production setup and operations

## Where the next features go

| Feature              | Lands in                                            |
| -------------------- | --------------------------------------------------- |
| Solana scanning      | `backend/app/services/scanner/` + a Celery task      |
| Token models         | `backend/app/models/token.py` + a migration          |
| AI scoring           | `backend/app/services/scoring/`                      |
| Discovery API        | `backend/app/api/v1/endpoints/tokens.py`             |
| Discovery UI         | `frontend/src/app/(dashboard)/tokens/`               |

Feature flags for the first two already exist in `app/core/config.py`
(`FEATURE_SCANNER_ENABLED`, `FEATURE_AI_SCORING_ENABLED`), defaulting to off.

# Development

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- Make
- Optional, for running outside containers: Python 3.12+, Node 20.11+, `uv`

## First run

```bash
make init
make up
make migrate
make seed
```

`make init` copies `.env.example` to `.env` and generates a `SECRET_KEY`.
`make seed` creates `admin@memescope.local` / `ChangeMeNow123!`.

## Daily workflow

```bash
make up                  # start
make logs S=backend      # tail one service
make check               # lint + typecheck + tests, same as CI
make down                # stop
```

Both services hot-reload against the bind-mounted source. Editing Python
restarts uvicorn; editing TSX triggers a fast refresh.

## Adding a feature

The order that keeps the layers honest:

1. **Model** — `app/models/<thing>.py`, exported from `app/models/__init__.py`.
2. **Migration** — `make migration M="add things"`, then *read the generated
   file*. Autogenerate misses enum value changes, server defaults, and data.
3. **Schema** — request/response types in `app/schemas/<thing>.py`.
4. **Repository** — queries in `app/repositories/<thing>.py`.
5. **Service** — business rules in `app/services/<thing>_service.py`.
6. **Router** — `app/api/v1/endpoints/<thing>.py`, registered in `router.py`.
7. **Tests** — a unit test for the service, an integration test for the route.
8. **Frontend** — types in `src/types/api.ts`, a query hook, then the UI.

If a step feels like it belongs in two layers, it belongs in the lower one.

## Testing

```bash
make test-backend               # everything
make test-unit                  # fast, no services needed
docker compose exec backend pytest tests/integration/test_auth_flow.py -v
docker compose exec backend pytest -k "refresh" -v
```

Integration tests use a real Postgres (`memescope_test`, created by the
Postgres init script). Each test runs inside a transaction that is rolled back,
so tests never see each other's data and order does not matter.

Frontend:

```bash
make test-frontend
docker compose exec frontend npm run test:watch
```

### What to test

- **Services** get unit tests — they are plain classes, no HTTP needed.
- **Routes** get integration tests covering the success path, the auth failure,
  and the validation failure.
- **Security behaviour** gets an explicit test. `test_auth_flow.py` asserts that
  refresh tokens rotate and that replaying an old one revokes every session.

## Code style

Backend: `ruff` for lint and format, `mypy --strict` for types. Both run in CI
and in the pre-commit hook.

```bash
make format
make lint
make typecheck
```

Frontend: ESLint with the Next.js config, Prettier for formatting, `tsc
--noEmit` for types.

Install the hooks once:

```bash
pip install pre-commit && pre-commit install
```

## Conventions

- Every endpoint declares `response_model` and a `summary`.
- Raise `AppError` subclasses, not `HTTPException`, so errors get the standard
  envelope and structured log line.
- Never log a token, password, or hash. Log the `user_id`.
- New environment variables go in three places: `Settings`, `.env.example`, and
  the compose `x-backend-env` block.
- Timestamps are `timestamptz` and UTC. Format at the edge, not in the database.

## Troubleshooting

**Backend restarts on boot** — Postgres is not ready yet. `scripts/entrypoint.sh`
waits, but a cold volume can exceed the start period. `make logs S=postgres`.

**`SECRET_KEY is required`** — `.env` is missing. Run `make init`.

**Migrations conflict after a rebase** — two heads. Check with
`docker compose exec backend alembic heads`, then merge with
`alembic merge -m "merge heads" <rev1> <rev2>`.

**Frontend cannot reach the API** — `NEXT_PUBLIC_API_URL` is inlined at build
time. Changing it requires a rebuild, not just a restart.

**Refresh loop / instant logout** — the browser is dropping the refresh cookie.
Locally, `REFRESH_COOKIE_SECURE` must be `false` (no TLS on localhost).

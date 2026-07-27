# MemeScope AI — Backend

FastAPI service providing the MemeScope AI API.

## Layout

```
app/
├── api/              HTTP layer — routers, dependencies. No business logic.
│   ├── deps.py       Shared dependencies (current user, role gates, services).
│   └── v1/           Versioned routes; add new areas under endpoints/.
├── core/             Cross-cutting concerns: config, logging, security, redis.
├── db/               Declarative base, mixins, engine, session dependency.
├── models/           SQLAlchemy ORM models. Import every model in __init__.py.
├── repositories/     Persistence queries. The only layer that writes SQL.
├── schemas/          Pydantic request/response contracts.
├── services/         Business rules. Orchestrates repositories; framework-free.
├── middleware/       Request context, rate limiting, security headers.
└── workers/          Celery app and background tasks.
```

The dependency direction is one-way: `api → services → repositories → models`.
A service never imports from `api`, and a repository never imports a service.
That is what keeps services unit-testable without an HTTP client.

## Running

Use the repository-root `make` targets (`make up`, `make migrate`, `make test`).
To work outside Docker:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

## Migrations

```bash
alembic revision --autogenerate -m "add tokens table"
alembic upgrade head
alembic downgrade -1
```

Always read the generated migration before committing it — autogenerate misses
enum value changes, server-default changes, and anything involving data.

## Conventions

- Every endpoint declares an explicit `response_model`.
- Errors are raised as `AppError` subclasses; handlers render the JSON envelope.
- New tables get a repository; new use cases get a service method.
- Anything slower than a request gets a Celery task, not a background thread.

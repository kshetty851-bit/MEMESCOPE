# Architecture

## Goals

The Day 1 foundation optimises for three things, in order:

1. **Changeability.** Meme coin discovery is a moving target. Layers are
   separated so a rewrite of the scanner does not touch auth, and a change to
   the token schema does not ripple into HTTP handlers.
2. **Operability.** Structured logs, request ids, health probes, and migrations
   exist from the first commit rather than being retrofitted after an incident.
3. **Safety.** Auth, rate limiting, and secret handling are settled once, up
   front, so feature work never has to re-decide them.

## Request lifecycle

```
Client
  │
  ▼
nginx  ─ TLS termination, coarse rate limit, static/API split
  │
  ▼
RequestContextMiddleware  ─ assigns X-Request-ID, binds the log context
  │
  ▼
CORS / TrustedHost / GZip
  │
  ▼
SecurityHeadersMiddleware
  │
  ▼
RateLimitMiddleware  ─ Redis fixed window, keyed by token or IP
  │
  ▼
Router (app/api/v1)  ─ validation, auth dependency, response model
  │
  ▼
Service (app/services)  ─ business rules, transaction-scoped
  │
  ▼
Repository (app/repositories)  ─ SQLAlchemy queries
  │
  ▼
PostgreSQL
```

Middleware is registered in reverse order of execution in `main.py`; request
context is added last so it wraps everything and every downstream log line
carries the id.

## Layers and their rules

| Layer          | May import                    | Must never                        |
| -------------- | ----------------------------- | --------------------------------- |
| `api/`         | schemas, services, deps       | write SQL                         |
| `services/`    | repositories, models, core    | import FastAPI or `Request`       |
| `repositories/`| models, db                    | contain business rules            |
| `models/`      | db                            | import services or schemas        |
| `core/`        | nothing app-specific          | import from any layer above       |

The payoff: a service is a plain class taking an `AsyncSession`, so it can be
tested without an HTTP client, and a repository can be swapped for a fake.

## Transactions

`get_db` owns the boundary. The session commits when a handler returns cleanly
and rolls back on any exception. Services call `flush()` — never `commit()` —
so a handler that raises after a successful service call writes nothing. One
request is one transaction.

## Authentication

Two-token design:

- **Access token** — JWT, 15 minutes, `Authorization: Bearer`. Carries `sub`,
  `jti`, `scopes`. Stateless: verifying it needs no database round trip.
- **Refresh token** — 48 bytes of entropy, 14 days, delivered as an httpOnly
  `SameSite=Lax` cookie scoped to `/api/v1/auth`. Only the SHA-256 digest is
  stored, so a database dump cannot be replayed.

**Rotation with reuse detection.** Every refresh issues a new token and revokes
the old one, recording `replaced_by_id`. Presenting an already-revoked token
means a copy leaked, so every session for that user is revoked and the client
must sign in again.

Why not put the access token in localStorage? Any XSS can read it. Why not put
it in a cookie too? Then every request needs CSRF protection. In-memory access
token plus httpOnly refresh cookie avoids both, at the cost of a refresh call on
page load — which `Providers` performs during bootstrap.

Revocation before expiry uses a Redis denylist keyed by `jti`, with a TTL equal
to the token's remaining life, so it cleans itself up.

## Data model

```
users                          refresh_tokens
─────                          ──────────────
id            uuid pk          id             uuid pk
email         unique           user_id        fk → users (cascade)
hashed_password                token_hash     unique, sha256
display_name                   expires_at
role          enum             revoked_at
is_active                      replaced_by_id fk → refresh_tokens
is_verified                    user_agent
last_login_at                  ip_address
created_at / updated_at        created_at / updated_at
```

UUID primary keys, not serial integers: they do not leak row counts, and they
let a scanner generate ids client-side without a round trip.

All timestamps are `timestamptz`. Everything is stored and computed in UTC;
formatting for a locale is the frontend's job.

## Caching and background work

Redis carries three responsibilities today — rate limit counters, the token
denylist, and the Celery broker/result backend. When feature work adds response
caching, it goes behind a small module in `core/` rather than scattering
`get_redis()` calls through services.

Celery Beat currently runs one job (purging expired refresh tokens). Scanner and
scoring jobs become additional tasks in `app/workers/`.

## Configuration

One `Settings` object, parsed once, validated at import. Production actively
refuses to boot on unsafe configuration: `DEBUG=true`, a short secret, wildcard
`ALLOWED_HOSTS`, or an insecure refresh cookie all raise. A crash at startup is
a far better outcome than a quietly insecure deployment.

## Observability

Every log line is JSON with a `request_id`; the same id is returned in the
`X-Request-ID` response header and embedded in every error envelope, so a user
report maps to log lines directly. nginx forwards an upstream id when present so
a trace survives the proxy hop.

`/live` never touches a dependency — a failing database must not cause a restart
loop. `/ready` checks Postgres and Redis and returns 503 when either is down, so
the load balancer stops sending traffic without the process dying.

## Deliberate omissions

- **No API gateway or service mesh.** Single deployable; premature at this size.
- **No OpenTelemetry yet.** Structured logs with request ids cover Day 1; tracing
  arrives when there is more than one service worth tracing across.
- **No read replicas.** Add when read load justifies it; the async engine and
  repository layer make the change local.
- **No email verification flow.** `is_verified` exists on the model so adding it
  later is a service change, not a migration plus a service change.

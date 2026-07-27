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

## Token discovery engine

Added Day 2. Runs as its own container (`scanner`), not inside the API: it is a
long-lived stateful stream consumer, and hosting it in the API would mean every
gunicorn worker opening a duplicate subscription.

```
Helius logsSubscribe (WebSocket)
  │  ~170k transactions per 10 min
  ▼
log pre-filter  ── requires an InitializeMint marker; drops 99.9%
  │
  ▼
bounded queue (2000)  ── drops newest on overflow, never blocks the socket
  │
  ▼
N workers ──▶ getTransaction  (retry: a confirmed tx is not instantly queryable)
          ──▶ getAsset (DAS)  (retry: the indexer lags confirmation)
          │
          ▼
    INSERT ... ON CONFLICT DO NOTHING
          │  returns a row only on genuine first insert
          ▼
    Redis publish ──▶ every API process ──▶ its WebSocket clients
```

**Why a bounded queue.** The stream delivers hundreds of transactions per second
while resolving one token costs two RPC round trips. Without decoupling, a burst
of launches would either block the socket read (getting us disconnected) or grow
memory without limit. On overflow the newest event is dropped and logged: a
scanner that dies under load is worse than one that misses a token.

**Why detection keys off `InitializeMint`.** A mint account cannot exist without
it, and it is emitted by both the SPL Token and Token-2022 programs. Keying off
a launchpad's own instruction name would break the moment that launchpad renamed
it — pump.fun already emits `CreateV2`, not `Create`.

**Idempotency** is enforced by the database, not by application code. The unique
index on `mint_address` plus `ON CONFLICT DO NOTHING` means two workers racing on
the same mint cannot both win, and no exception is raised for the loser. The
insert returns a row only on a genuine first insert, which is exactly the signal
for "should this be broadcast?". A Redis `SET NX` check runs first purely to
avoid a wasted database round trip; it is an optimisation, not the guarantee.

**Metadata is never a blocker.** A token whose metadata has not been indexed yet
is stored with `metadata_status=pending`. Losing a discovery would be far worse
than storing a row whose name arrives a few seconds later.

### Event fan-out

The scanner and the API are separate processes, so an in-memory callback list
would only reach clients connected to the publishing process. Redis pub/sub
carries each discovery to every API process, and each process fans out to its
own WebSocket clients — one Redis subscription per process regardless of client
count.

Each subscriber has a bounded queue. A client too slow to keep up has messages
dropped rather than being allowed to grow a backlog: a live feed is only useful
while it is live.

## Data model

```
discovered_tokens
─────────────────
id               uuid pk
mint_address     unique, indexed   ← natural key; makes ingestion idempotent
name / symbol / decimals / metadata_uri
creator_address  indexed           ← transaction fee payer
signature        indexed
slot             bigint            ← exceeds 32-bit range
block_time       indexed           ← on-chain creation time
discovered_at    indexed, desc     ← when this system first saw it
source_program   indexed
metadata_status  enum(pending|resolved|failed)
metadata_attempts
created_at / updated_at
```

Both timestamps are kept deliberately: the gap between `block_time` and
`discovered_at` is ingestion latency, worth measuring rather than inferring.

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

## Scanner failure modes

| Failure                  | Handling                                                |
| ------------------------ | ------------------------------------------------------- |
| Helius WebSocket drops   | Reconnect with exponential backoff + full jitter; a clean connection resets the ladder. |
| Transaction not yet queryable | Polled up to `SCANNER_TX_FETCH_ATTEMPTS` times with backoff. |
| DAS metadata not indexed | Polled up to `SCANNER_METADATA_ATTEMPTS`; then stored `pending`. |
| Partial DAS response     | Every metadata field is optional; a missing symbol never discards a mint. |
| Rate limited (429) / 5xx | Retried with backoff. A JSON-RPC application error is not retried — it would fail identically. |
| Duplicate events         | Redis `SET NX`, then the unique index as the real guarantee. |
| Redis unavailable        | Dedupe fails open; discovery continues, the database still rejects duplicates. |
| Burst of launches        | Bounded queue sheds the newest events and logs `scanner_queue_full`. |
| Malformed metadata       | NUL-stripped, trimmed, truncated before storage. |
| Failed on-chain tx       | Skipped — a reverted mint never existed. |

Full jitter rather than plain doubling: when Helius recovers from an outage,
every reconnecting client would otherwise retry in lockstep and knock it over
again.

## Deliberate omissions

- **No API gateway or service mesh.** Single deployable; premature at this size.
- **No OpenTelemetry yet.** Structured logs with request ids cover Day 1; tracing
  arrives when there is more than one service worth tracing across.
- **No read replicas.** Add when read load justifies it; the async engine and
  repository layer make the change local.
- **No email verification flow.** `is_verified` exists on the model so adding it
  later is a service change, not a migration plus a service change.

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

## Token enrichment engine

Added Day 3. A second independent worker (`enrichment`), separate from both the
API and the scanner. Discovery must never wait on market data, and a provider
outage must never stop tokens being found.

```
scanner ──publish──▶ Redis channel ──▶ enrichment listener ──▶ enrol in schedule
                                                                     │
                     ┌───────────────────────────────────────────────┘
                     ▼
        token_enrichment_state (work queue)
                     │  claim_due: FOR UPDATE SKIP LOCKED + lease
                     ▼
            MarketEnrichmentService
                     │  batches of 30 mints
                     ▼
            MarketDataProvider (ABC) ──▶ DexScreenerProvider
                     │                      retry · breaker · timeout
                     ▼
        token_market_snapshots (append-only)
                     │
                     ▼
              REST API ──▶ frontend
```

**Two inputs, one queue.** The Redis listener enrols a token the instant the
scanner publishes it, so enrichment begins within milliseconds. The database
queue drives every subsequent refresh. A backfill sweep enrols any token that
has no scheduling row, at startup **and every 5 minutes after**. The listener is
the fast path, not a guarantee: it only sees events published while it is
connected, so a startup-only sweep leaves orphans behind after a Redis blip or a
worker restart. Live verification found 1,411 tokens stranded that way; the
periodic sweep took it to zero.

**Why a database queue rather than a Redis queue.** The work is recurring, not
one-shot: each token needs re-enqueueing forever on a schedule that depends on
its age. A durable row with `next_refresh_at` expresses that directly, survives
restarts, and makes "what is due?" a single indexed query. `FOR UPDATE SKIP
LOCKED` with a lease lets multiple worker replicas claim disjoint sets, and a
worker that dies mid-batch releases its tokens when the lease expires rather
than stranding them.

**Batching is load-bearing.** DexScreener accepts 30 mints per request. Fetching
one at a time would be 30× the requests for identical data and would not fit
inside the rate limit at this token volume. `fetch_many` is therefore the
primitive in the provider interface, not an optimisation bolted on later.

### Provider abstraction

Nothing above `app/services/market/providers/` sees vendor JSON. See
[ADR 0001](adr/0001-market-provider-abstraction.md) for the full reasoning.

### Adaptive refresh

A token's information value decays sharply with age, so refresh cadence follows
it. Every boundary is configurable.

| Tier   | Age            | Interval | Rationale                                  |
| ------ | -------------- | -------- | ------------------------------------------ |
| fresh  | < 30 min       | 30s      | The window that decides whether it is anything |
| young  | 30 min – 6 h   | 5 min    | Still moving, no longer second-by-second    |
| mature | 6 – 24 h       | 30 min   | Trend, not tick                             |
| old    | > 24 h         | 6 h      | Kept current, cheaply                       |

Without tiering, old tokens would consume the entire provider budget within days
purely by outnumbering new ones.

Two distinct backoff paths sit on top:

- **Failure** (provider error) backs off exponentially, floored at the tier's own
  interval so a broken token is never polled *more* than a healthy one.
- **Empty** (no pool indexed yet) eases off linearly and is capped at the mature
  interval. This is the normal state for a token seconds old — roughly half of
  brand-new mints are not yet indexed — and treating it as an error would
  dead-letter perfectly healthy tokens.

### Snapshots, not overwrites

`token_market_snapshots` is append-only. Every successful refresh inserts a row;
nothing is ever updated. That is what makes price history, volume trends, and
later backtesting possible at all — an overwriting `current_market` table would
throw away the only data that answers "what happened".

A snapshot is written only when the provider actually returned market data. A
token with no pool records the *attempt* on its state row (`consecutive_empty`,
`last_attempt_at`) rather than inserting a row of NULLs, which would bloat the
history table with no information.

Money is `NUMERIC`, never float. Meme coin prices run to 1e-12 and market caps
to 1e10; binary floating point cannot represent decimal fractions exactly and the
error compounds across millions of rows. The API serialises them as JSON strings
and the frontend keeps them as strings until the moment of display.

## Data model

```
token_market_snapshots  (append-only history)
──────────────────────
id                        uuid pk
token_id                  fk → discovered_tokens (cascade)
mint_address              denormalised, so history needs no join
captured_at               indexed DESC
price_usd / price_native  NUMERIC(38,18)
liquidity_usd, fully_diluted_valuation, market_cap   NUMERIC(24,4)
volume_24h / volume_1h / volume_5m                   NUMERIC(24,4)
buy_count_24h, sell_count_24h
dex_name, trading_pair, pool_address
trading_status            enum(unknown|trading|inactive)
is_verified
provider                  provenance across vendor migrations
provider_latency_ms

token_enrichment_state  (scheduler work queue, one row per token)
──────────────────────
id                    uuid pk
token_id              fk → discovered_tokens, unique
mint_address          unique
status                enum(active|dead_letter|paused)
next_refresh_at       the hot column; drives every claim
last_attempt_at / last_success_at
consecutive_failures  → exponential backoff, then dead-letter
consecutive_empty     → linear backoff (not an error)
total_refreshes / total_snapshots
last_error, tier
```

Indexes are shaped around the three real queries:
`(mint_address, captured_at DESC)` for history and the `DISTINCT ON` that
resolves each token's latest snapshot; `captured_at DESC` for trending; and
`(status, next_refresh_at)` for the claim query.

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

## Enrichment failure modes

| Failure                       | Handling                                          |
| ----------------------------- | ------------------------------------------------- |
| Provider timeout / 5xx        | Retried with exponential backoff + full jitter.    |
| Provider 429                  | Retried; counts towards the circuit breaker.       |
| Provider 4xx (our bug)        | Not retried — it would fail identically.           |
| Provider persistently down    | Circuit opens after 5 consecutive failures, fails fast for 60s, then admits a single probe (half-open) and closes only after 2 successes. |
| Token with no indexed pool    | Empty result, not an error. Linear backoff, capped. |
| Partial payload               | Every `MarketData` field is optional; a missing symbol never discards a mint. |
| Junk values (NaN, strings)    | Coerced to `None` at the adapter boundary.        |
| Repeated failure on one token | Dead-lettered after 10 consecutive failures; retained and requeueable, not deleted. |
| Worker crash mid-batch        | Claim lease expires; tokens return to the queue.   |
| Redis down                    | Listener reconnects with backoff. The database queue keeps working, so enrichment continues — only the "enrol immediately on discovery" latency is lost. |
| Whole provider outage         | `refresh_degraded` logged, every token rescheduled with backoff, worker stays up. Discovery is entirely unaffected. |

The circuit breaker exists because retrying a dead provider is worse than
useless: it burns the worker's time and adds load to something already
struggling. Failing fast for a cooldown and probing once is strictly better.

## Deliberate omissions

- **No API gateway or service mesh.** Single deployable; premature at this size.
- **No OpenTelemetry yet.** Structured logs with request ids cover Day 1; tracing
  arrives when there is more than one service worth tracing across.
- **No read replicas.** Add when read load justifies it; the async engine and
  repository layer make the change local.
- **No email verification flow.** `is_verified` exists on the model so adding it
  later is a service change, not a migration plus a service change.

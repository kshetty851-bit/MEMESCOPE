# API

Base URL: `http://localhost:8000`
Versioned prefix: `/api/v1`
Interactive docs: `/docs` (disabled in production)

## Conventions

- JSON in, JSON out; `snake_case` field names.
- Timestamps are ISO 8601 UTC.
- Ids are UUIDv4 strings.
- Every response carries `X-Request-ID`. Quote it in bug reports.

## Errors

Every failure — validation, auth, not found, unhandled — uses one envelope:

```json
{
  "error": {
    "code": "conflict",
    "message": "An account with that email already exists.",
    "details": {}
  },
  "request_id": "0f6b1c2e-..."
}
```

Branch on `code`, never on `message`.

| Code                   | HTTP | Meaning                                     |
| ---------------------- | ---- | ------------------------------------------- |
| `validation_error`     | 422  | Payload failed validation; see `details`     |
| `authentication_error` | 401  | Missing, invalid, or expired credentials     |
| `token_expired`        | 401  | Access token expired — refresh and retry     |
| `token_revoked`        | 401  | Token was explicitly revoked                 |
| `token_reuse_detected` | 401  | Rotated refresh token replayed; all sessions revoked |
| `permission_denied`    | 403  | Authenticated but not allowed                |
| `not_found`            | 404  | No such resource                             |
| `conflict`             | 409  | Uniqueness violation                         |
| `rate_limited`         | 429  | Slow down; see `Retry-After`                 |
| `internal_error`       | 500  | Unexpected; the `request_id` locates the log |

## Authentication flow

```
register / login  ──►  { access_token, expires_in, user }
                       + Set-Cookie: memescope_refresh (httpOnly)

authenticated call ──►  Authorization: Bearer <access_token>

on 401             ──►  POST /auth/refresh  (cookie sent automatically)
                        ──► new access_token + rotated cookie

logout             ──►  revokes the refresh token, clears the cookie
```

The access token lives ~15 minutes and is kept in memory by the client. The
refresh token lives 14 days in an httpOnly cookie and **rotates on every use** —
replaying an old one revokes every session for that user.

## Endpoints

### Health

| Method | Path                       | Auth | Description                                |
| ------ | -------------------------- | ---- | ------------------------------------------ |
| GET    | `/live`                    | —    | Process is up. Never touches dependencies. |
| GET    | `/ready`                   | —    | Postgres + Redis reachable. 503 if not.    |
| GET    | `/api/v1/health/pipeline`  | —    | Per-stage pipeline health. 503 when down.  |

`/live` and `/ready` are also mounted under `/api/v1`.

`/health/pipeline` answers a different question from both: not "is this process
serving" but "is the platform still producing anything". Every figure is derived
from persisted state — the last row each stage wrote — because a stage's process
being alive is precisely the signal that failed. Discovery once stopped for four
days while `/live`, `/ready` and the container status all stayed green.

Each of `scanner`, `market_enrichment`, `scoring` and `radar` reports a
`status` of `healthy`, `degraded` or `down`, the timestamp it was last known to
produce output, and the minutes since. Stage-specific depth is included:
enrichment reports `queue_depth` and `dead_lettered`, scoring reports `pending`
(tokens with observations but no score), the Radar reports `tracked_tokens`.
The scanner additionally reports `reconnect_attempts` and `failure_reason`,
published by the scanner process itself — a scanner that cannot reach Helius is
degraded even when its last discovery is recent.

`overall` is the worst status among **enabled** stages, so a deployment that
deliberately runs no scanner is not permanently degraded. The endpoint returns
`503` when `overall` is `down` and `200` when it is `degraded`, so an external
monitor can page without parsing the body — and is not trained to ignore a
warning.

Thresholds are configurable per stage via `HEALTH_<STAGE>_DEGRADED_MINUTES` and
`HEALTH_<STAGE>_DOWN_MINUTES`. The scanner's container healthcheck
(`python -m app.health.probe`) reads the same values, so Docker and the
dashboard cannot disagree about whether discovery is down.

```json
{
  "scanner": {
    "status": "down",
    "last_discovery": "2026-07-29T13:19:08.739931Z",
    "minutes_since_last_token": 6029.2,
    "reconnect_attempts": 7,
    "failure_reason": "InvalidStatus: server rejected WebSocket connection: HTTP 429"
  },
  "market_enrichment": {
    "status": "healthy",
    "last_snapshot": "2026-08-02T17:35:14.014146Z",
    "minutes_since_last_snapshot": 1.2,
    "queue_depth": 0,
    "dead_lettered": 5
  },
  "scoring": {
    "status": "healthy",
    "last_score": "2026-08-02T17:38:02.996678Z",
    "minutes_since_last_score": 10.3,
    "pending": 2880
  },
  "radar": {
    "status": "healthy",
    "last_cycle": "2026-08-02T17:45:00.028538Z",
    "minutes_since_last_cycle": 3.4,
    "tracked_tokens": 41
  },
  "overall": "down",
  "environment": "local",
  "version": "0.8.0-rc1",
  "observed_at": "2026-08-02T17:48:23.467883Z"
}
```

### Auth

| Method | Path                    | Auth   | Description                        |
| ------ | ----------------------- | ------ | ---------------------------------- |
| POST   | `/api/v1/auth/register` | —      | Create an account, start a session |
| POST   | `/api/v1/auth/login`    | —      | Exchange credentials for tokens    |
| POST   | `/api/v1/auth/refresh`  | cookie | Rotate the refresh token           |
| POST   | `/api/v1/auth/logout`   | cookie | End the current session            |
| POST   | `/api/v1/auth/logout-all` | bearer | Revoke every session             |

### Users

| Method | Path                       | Auth   | Description                      |
| ------ | -------------------------- | ------ | -------------------------------- |
| GET    | `/api/v1/users/me`         | bearer | Current user                     |
| PATCH  | `/api/v1/users/me`         | bearer | Update display name              |
| POST   | `/api/v1/users/me/password`| bearer | Change password; revokes sessions|

### Tokens (discovery engine)

Public — discovered tokens are public chain data, so no bearer token is needed.

| Method | Path                        | Description                              |
| ------ | --------------------------- | ---------------------------------------- |
| GET    | `/api/v1/tokens`            | List with pagination, sorting, filtering |
| GET    | `/api/v1/tokens/latest`     | Most recent discoveries, newest first    |
| GET    | `/api/v1/tokens/{mint}`     | One token by mint address                |
| WS     | `/api/v1/tokens/stream`     | Live discovery feed                      |

#### Token object

```json
{
  "id": "8bca69c5-f07d-4f8e-8f48-fc133dc2016e",
  "mint_address": "DfBEf7sTQTS3kXfuR4J47E9zwzoTfzbzCo1YEypPpump",
  "name": "at",
  "symbol": "at",
  "decimals": 6,
  "metadata_uri": "https://ipfs.io/ipfs/QmZhYsShK8FA78fVwtzw6FMkUFCA5vCMueFUx6PquZowP9",
  "creator_address": "4UKLdTBiz6pGRccq9CGw9n53UwmAdd4UX1sJKeUohSiP",
  "signature": "5WoivgEPg25m2AA2p1Hgqo1XH1co8rmew19833woUUL9TKpnn4kuzCfvXEuuhZx4m3RzCGpzrAtwc7DwVFumevYB",
  "slot": 435487181,
  "block_time": "2026-07-27T06:31:43Z",
  "discovered_at": "2026-07-27T06:31:45.220325Z",
  "source_program": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
  "metadata_status": "resolved"
}
```

`block_time` is when the token was created on-chain. `discovered_at` is when
MemeScope first saw it. `metadata_status` is `pending` when off-chain metadata
has not been indexed yet — the token is still recorded, and `name`/`symbol` may
be `null`.

#### `GET /api/v1/tokens`

| Query param         | Type     | Default         | Notes                              |
| ------------------- | -------- | --------------- | ---------------------------------- |
| `page`              | int ≥ 1  | `1`             |                                    |
| `page_size`         | 1–100    | `20`            |                                    |
| `sort_by`           | enum     | `discovered_at` | `discovered_at`, `block_time`, `slot`, `name`, `symbol` |
| `order`             | enum     | `desc`          | `asc`, `desc`                      |
| `created_after`     | datetime | —               | On-chain creation lower bound      |
| `created_before`    | datetime | —               | On-chain creation upper bound      |
| `discovered_after`  | datetime | —               | Discovery lower bound              |
| `discovered_before` | datetime | —               | Discovery upper bound              |
| `symbol`            | string   | —               | Case-insensitive exact match       |
| `creator_address`   | string   | —               | Exact match                        |
| `metadata_status`   | enum     | —               | `pending`, `resolved`, `failed`    |

Response:

```json
{ "items": [ /* tokens */ ], "total": 130, "page": 1, "page_size": 20, "pages": 7 }
```

An inverted range (`created_after` later than `created_before`) returns 422.

> **Encoding note.** A `+00:00` offset must be percent-encoded (`%2B00:00`) or
> the `+` is decoded as a space and the request fails validation. Using the `Z`
> suffix (`2026-07-27T06:30:00Z`) avoids the issue entirely.

#### `GET /api/v1/tokens/latest`

`limit` (1–100, default 20). Returns a bare array, newest first.

#### `GET /api/v1/tokens/{mint}`

`mint` must be base58, 32–44 characters; anything else returns 422 before the
database is touched. Unknown mints return 404 with the standard envelope.

#### `WS /api/v1/tokens/stream`

Frames are JSON objects with a `type`:

```json
{"type": "connection.ready", "message": "Streaming discoveries."}
{"type": "token.discovered", "data": { /* token object */ }}
{"type": "ping"}
```

`ping` is a keepalive sent after ~25s of silence so idle proxies do not close the
connection. Anything the client sends is ignored. Clients should reconnect with
backoff; the server drops messages for consumers that fall too far behind rather
than buffering without limit.

```bash
websocat ws://localhost:8000/api/v1/tokens/stream
```

### Market (enrichment engine)

Public, like the rest of the token API.

| Method | Path                          | Description                          |
| ------ | ----------------------------- | ------------------------------------ |
| GET    | `/api/v1/tokens/{mint}/market`  | Current market state for a token   |
| GET    | `/api/v1/tokens/{mint}/history` | Historical snapshots, newest first |
| GET    | `/api/v1/market/trending`       | Tokens ranked by latest snapshot   |

#### Money is a string, not a number

Every monetary field is serialised as a JSON **string** (`"0.017840000000000000"`).
The database stores `NUMERIC`, and rendering it as a JSON number would push it
through a float and silently destroy precision on prices around 1e-12. Parse it
with a decimal library; convert to a float only for display.

#### Snapshot object

```json
{
  "id": "6bcac987-b5d4-4b16-af9d-05abf08f73f6",
  "mint_address": "cRyAiogmFhGKkZafqNKaoTqZCdTP8432VtRWEAEpump",
  "captured_at": "2026-07-27T13:59:12.441Z",
  "price_usd": "0.017840000000000000",
  "price_native": "0.000196400000000000",
  "liquidity_usd": "308900.5300",
  "fully_diluted_valuation": "17850000.0000",
  "market_cap": "17850000.0000",
  "volume_24h": "175100.4900",
  "volume_1h": "175100.4900",
  "volume_5m": "19200.1700",
  "buy_count_24h": 1317,
  "sell_count_24h": 138,
  "dex_name": "pumpswap",
  "trading_pair": "USWR/SOL",
  "pool_address": "HxQ2...4Lps",
  "trading_status": "trading",
  "is_verified": true,
  "provider": "dexscreener",
  "provider_latency_ms": 341
}
```

`captured_at` is the "last updated" timestamp. `trading_status` is one of
`unknown` (no pool indexed yet), `trading`, or `inactive` (indexed but with
negligible liquidity). Any field may be `null` — providers return partial data
routinely, and a missing value never discards the observation.

#### `GET /api/v1/tokens/{mint}/market`

```json
{
  "mint_address": "cRyAiog…pump",
  "market": { /* snapshot, or null */ },
  "snapshot_count": 18,
  "last_refreshed_at": "2026-07-27T13:59:12.441Z",
  "next_refresh_at": "2026-07-27T13:59:42.441Z",
  "enrichment_status": "active",
  "tier": "fresh"
}
```

`market` is `null` when the provider has not indexed a pool yet. That is a
**200, not a 404** — the token exists, its market does not yet. A 404 means the
token was never discovered.

`enrichment_status` is `active`, `dead_letter`, or `paused`. `tier` is the
adaptive refresh band: `fresh`, `young`, `mature`, or `old`.

#### `GET /api/v1/tokens/{mint}/history`

| Query param | Type     | Default | Notes                       |
| ----------- | -------- | ------- | --------------------------- |
| `page`      | int ≥ 1  | `1`     |                             |
| `page_size` | 1–500    | `50`    |                             |
| `since`     | datetime | —       | Lower bound on `captured_at` |
| `until`     | datetime | —       | Upper bound on `captured_at` |

```json
{ "mint_address": "…", "items": [ /* snapshots */ ],
  "total": 18, "page": 1, "page_size": 50, "pages": 1 }
```

Newest first. An inverted window (`since` after `until`) returns 422.

#### `GET /api/v1/market/trending`

One entry per token, using its most recent snapshot.

| Query param     | Type    | Default      | Notes                                    |
| --------------- | ------- | ------------ | ---------------------------------------- |
| `page`          | int ≥ 1 | `1`          |                                          |
| `page_size`     | 1–100   | `20`         |                                          |
| `sort_by`       | enum    | `volume_24h` | also `volume_1h`, `volume_5m`, `liquidity_usd`, `market_cap`, `price_usd`, `captured_at` |
| `min_liquidity` | float   | —            | Drop pools below this USD liquidity      |
| `since`         | datetime| —            | Only consider snapshots after this time  |

```json
{
  "items": [{ "token": { /* token */ }, "market": { /* snapshot */ } }],
  "total": 30, "page": 1, "page_size": 20, "pages": 2,
  "sort_by": "volume_24h"
}
```

Tokens with a `null` value for the sort field rank last, so a token with no
recorded volume never outranks one that has volume.

`sort_by=captured_at` ranks by observation recency rather than size — the live
feed uses it to pick up market data for tokens that are new and low-volume,
which a volume ranking would bury.

```bash
curl -s "http://localhost:8000/api/v1/market/trending?sort_by=liquidity_usd&min_liquidity=1000&page_size=5"
```

## Examples

Register:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -c cookies.txt \
  -d '{"email":"trader@example.com","password":"SuperSecret123!","display_name":"Trader"}'
```

Call a protected route:

```bash
curl http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Refresh (the cookie jar carries the refresh token):

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh -b cookies.txt -c cookies.txt
```

## Rate limits

Default 120 requests per 60 seconds, keyed by access token when present and by
IP otherwise. Health and docs paths are exempt. Responses carry
`X-RateLimit-Limit` and `X-RateLimit-Remaining`; a 429 adds `Retry-After`.

If Redis is unavailable the limiter fails open — availability of the API is
worth more than perfect enforcement, and nginx still applies a coarser limit.

## Password rules

Minimum 12 characters, with at least one letter and one digit. Enforced server
side in `app/schemas/user.py`; the register form mirrors the length check for
immediate feedback.

## Not yet implemented

Watchlists and AI scoring endpoints do not exist yet. They will live under
`/api/v1/watchlists` and `/api/v1/signals`.

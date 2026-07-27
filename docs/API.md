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

| Method | Path     | Auth | Description                                |
| ------ | -------- | ---- | ------------------------------------------ |
| GET    | `/live`  | —    | Process is up. Never touches dependencies. |
| GET    | `/ready` | —    | Postgres + Redis reachable. 503 if not.    |

Both are also mounted under `/api/v1`.

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

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

Token discovery, scanning, watchlists, and AI scoring endpoints do not exist on
Day 1. They will live under `/api/v1/tokens`, `/api/v1/watchlists`, and
`/api/v1/signals`.

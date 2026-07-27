"""Password hashing and JWT issuance/verification.

Design notes:
  * Access tokens are short-lived JWTs carried in the `Authorization` header.
  * Refresh tokens are opaque random strings; only their SHA-256 digest is
    stored, so a database leak cannot be replayed against the API.
  * Every access token carries a `jti`, which lets us revoke individual tokens
    through the Redis denylist without waiting for natural expiry.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import AuthenticationError

TokenType = Literal["access", "refresh"]

# bcrypt truncates at 72 bytes; hash long inputs first so entropy is preserved.
_BCRYPT_MAX_BYTES = 72


@dataclass(frozen=True, slots=True)
class TokenPayload:
    subject: str
    token_type: TokenType
    jti: str
    issued_at: datetime
    expires_at: datetime
    scopes: tuple[str, ...] = ()


def _prepare_password(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare_password(password), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare_password(password), password_hash.encode())
    except ValueError:
        # Malformed hash in the database — treat as a failed login, never a 500.
        return False


def create_access_token(
    subject: str | uuid.UUID,
    *,
    scopes: list[str] | None = None,
    expires_delta: timedelta | None = None,
) -> tuple[str, TokenPayload]:
    return _create_token(
        subject,
        token_type="access",
        expires_delta=expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        scopes=scopes or [],
    )


def create_refresh_token() -> tuple[str, str, datetime]:
    """Return `(plaintext, sha256_digest, expires_at)` for a new refresh token."""
    plaintext = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return plaintext, hash_refresh_token(plaintext), expires_at


def hash_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _create_token(
    subject: str | uuid.UUID,
    *,
    token_type: TokenType,
    expires_delta: timedelta,
    scopes: list[str],
) -> tuple[str, TokenPayload]:
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())
    claims: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.PROJECT_NAME,
        "scopes": scopes,
    }
    encoded = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    payload = TokenPayload(
        subject=str(subject),
        token_type=token_type,
        jti=jti,
        issued_at=now,
        expires_at=expires_at,
        scopes=tuple(scopes),
    )
    return encoded, payload


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate an access token, or raise `AuthenticationError`."""
    try:
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.PROJECT_NAME,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Access token is invalid.", code="token_invalid") from exc

    if claims.get("type") != "access":
        raise AuthenticationError("Expected an access token.", code="token_invalid")

    return TokenPayload(
        subject=claims["sub"],
        token_type="access",
        jti=claims["jti"],
        issued_at=datetime.fromtimestamp(claims["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
        scopes=tuple(claims.get("scopes", ())),
    )

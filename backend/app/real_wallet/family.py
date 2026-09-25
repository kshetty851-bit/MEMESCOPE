"""The family pages: who the members are, their trade sizes, and the password.

Jaya, Asha and Apoorva each have a Solana wallet of their own
(`family_wallets`), trading on its own switch. The SHARES of the owner's
wallet this module used to size, split and account for were removed on
2026-09-25 at Karthik's request, once the members had wallets of their own:
the owner's orders are his own ticket again, and nothing here touches them.

## The password

Only a PBKDF2 hash lives on the server (`REAL_WALLET_FAMILY_PASSWORD_HASH`,
`salt_hex:hash_hex`). The repository is public, so the password is never in
it, and the format has no `$` in it because docker compose interpolates `$` in
an env file and would silently mangle a bcrypt hash. A correct password buys a
short-lived token for ONE member, carried in `X-Family-Token`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jwt

from app.core.config import settings

MEMBERS: tuple[str, ...] = ("JAYA", "ASHA", "APOORVA")
#: The trade sizes a member's own wallet may be set to.
TICKETS_USD: tuple[Decimal, ...] = tuple(
    Decimal(t) for t in ("10", "20", "25", "50", "100", "200"))
TOKEN_HOURS = 12
_PBKDF2_ROUNDS = 600_000


# --- the password and the token ---------------------------------------------

def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """`salt_hex:hash_hex`. Used once, by hand, to produce the server setting."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"{salt.hex()}:{digest.hex()}"


def password_ok(password: str, stored: str | None = None) -> bool:
    stored = (settings.REAL_WALLET_FAMILY_PASSWORD_HASH if stored is None else stored).strip()
    if not stored or ":" not in stored:
        return False            # no password configured: nobody gets in
    salt_hex, want_hex = stored.split(":", 1)
    try:
        salt, want = bytes.fromhex(salt_hex), bytes.fromhex(want_hex)
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return hmac.compare_digest(got, want)


def issue_token(member: str, *, now: datetime | None = None) -> tuple[str, datetime]:
    now = now or datetime.now(UTC)
    expires = now + timedelta(hours=TOKEN_HOURS)
    token = jwt.encode({"type": "family", "sub": member, "iat": int(now.timestamp()),
                        "exp": int(expires.timestamp()), "iss": settings.PROJECT_NAME},
                       settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires


def token_member(token: str | None) -> str | None:
    """The member a token was issued for, or None if it is not a valid one."""
    if not token:
        return None
    try:
        claims = jwt.decode(token, settings.SECRET_KEY,
                            algorithms=[settings.JWT_ALGORITHM],
                            issuer=settings.PROJECT_NAME,
                            options={"require": ["exp", "iat", "sub"]})
    except jwt.InvalidTokenError:
        return None
    if claims.get("type") != "family" or claims.get("sub") not in MEMBERS:
        return None
    return claims["sub"]


class Throttle:
    """At most `limit` wrong passwords per caller per `window` seconds.

    ponytail: in memory and per process, so a restart forgets and each API
    worker counts alone. Enough to make guessing a slow job for one person;
    move it to Redis if the family page is ever exposed beyond the site gate.
    """

    def __init__(self, limit: int = 5, window: float = 600.0) -> None:
        self.limit, self.window = limit, window
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def blocked(self, who: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self._fails[who]
        while q and now - q[0] > self.window:
            q.popleft()
        return len(q) >= self.limit

    def failed(self, who: str, *, now: float | None = None) -> None:
        self._fails[who].append(time.monotonic() if now is None else now)


THROTTLE = Throttle()

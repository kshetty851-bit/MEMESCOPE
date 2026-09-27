"""The user wallets: who they are, and the trade sizes one may be set to.

USER 1 … USER 10 (Karthik, 2026-09-27: "remove family wallets and give list
of 10 wallets in sequence, just name it USER 1, USER 2 etc") each have a
Solana wallet of their own (`family_wallets`) that copies the strategy he
nominated at Start, on its own switch and size. The module and table keep
their "family" names; the people in them are now numbered.

Only Karthik, signed in as the admin, can see or touch these wallets. USER 2
to USER 10, and the fees, sit behind a second lock as well (Karthik,
2026-09-27): a password of his own, kept on the server only as a PBKDF2 hash
(`REAL_WALLET_USERS_PASSWORD_HASH`, `salt_hex:hash_hex`, no `$` because
compose would mangle it; the repository is public). The right password buys a
12-hour token, sent as `X-Users-Token`. USER 1 stays open to his sign-in.
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

MEMBERS: tuple[str, ...] = tuple(f"USER{i}" for i in range(1, 11))
#: The trade sizes a user's wallet may be set to.
TICKETS_USD: tuple[Decimal, ...] = tuple(
    Decimal(t) for t in ("10", "20", "25", "50", "100", "200"))


#: The one user wallet the second lock leaves open.
OPEN_MEMBERS: frozenset[str] = frozenset({"USER1"})
TOKEN_HOURS = 12
_PBKDF2_ROUNDS = 600_000


def locked(member: str) -> bool:
    return member not in OPEN_MEMBERS


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """`salt_hex:hash_hex`. Used once, by hand, to produce the server setting."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"{salt.hex()}:{digest.hex()}"


def password_ok(password: str, stored: str | None = None) -> bool:
    stored = (settings.REAL_WALLET_USERS_PASSWORD_HASH if stored is None else stored).strip()
    if not stored or ":" not in stored:
        return False            # no password configured: nobody gets in
    salt_hex, want_hex = stored.split(":", 1)
    try:
        salt, want = bytes.fromhex(salt_hex), bytes.fromhex(want_hex)
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return hmac.compare_digest(got, want)


def issue_token(*, now: datetime | None = None) -> tuple[str, datetime]:
    now = now or datetime.now(UTC)
    expires = now + timedelta(hours=TOKEN_HOURS)
    token = jwt.encode({"type": "users", "sub": "users", "iat": int(now.timestamp()),
                        "exp": int(expires.timestamp()), "iss": settings.PROJECT_NAME},
                       settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires


def token_ok(token: str | None) -> bool:
    if not isinstance(token, str) or not token:
        return False
    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
                            issuer=settings.PROJECT_NAME,
                            options={"require": ["exp", "iat", "sub"]})
    except jwt.InvalidTokenError:
        return False
    return claims.get("type") == "users"


class Throttle:
    """At most `limit` wrong passwords per caller per `window` seconds.

    ponytail: in memory and per process, so a restart forgets and each API
    worker counts alone. Behind the admin sign-in already, so enough.
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


def label(member: str) -> str:
    """"USER7" -> "USER 7", for people to read."""
    return member.replace("USER", "USER ", 1)

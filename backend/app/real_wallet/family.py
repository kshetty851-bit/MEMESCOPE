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
12-hour token, sent as `X-Users-Token`. Since 2026-09-28 USER 1-7 (the family
investment) have a password of their own; see `INVESTMENT_MEMBERS`.
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

#: Coin-size bands a user wallet may be set to, by market cap (FDV) at the
#: moment it would buy: key -> (at least, under), None = no bound. From the
#: Karthik's Lab trades by size (2026-09-28): $1-5M coins returned most and
#: $100M+ were the only ones that lost, and a $100 buy moves a small coin's
#: price twice as far as a $50 one — so the $100 wallets start at $5M.
BANDS: dict[str, tuple[Decimal | None, Decimal | None]] = {
    "any": (None, None),
    "1m-20m": (Decimal(1_000_000), Decimal(20_000_000)),
    "5m-100m": (Decimal(5_000_000), Decimal(100_000_000)),
}
#: SMART STACKING (Karthik, 2026-10-10: "build smart stacking for 3 wallets
#: before nov 1"): bands by POOL size (liquidity) at the moment of buying, so
#: more wallets stack on the small pools that earn the most and fewer on the
#: big ones that earn about nothing. key -> pool under this many dollars.
#: 3 wallets = one "any" + two "pool-under-150k" (3/3/1 on small/mid/big
#: pools); 6 wallets = two "any" + one "pool-under-150k" + three
#: "pool-under-75k" (5/3/2 with the $250 coin cap). Replayed 1-10 Oct: 3x$50
#: +$1,159 against +$1,112 for all three on every coin. Chosen on those days.
POOL_BANDS: dict[str, Decimal] = {
    "pool-under-75k": Decimal(75_000),
    "pool-under-150k": Decimal(150_000),
}
BAND_LABELS: dict[str, str] = {"any": "Any size", "1m-20m": "$1M – $20M",
                               "5m-100m": "$5M – $100M",
                               "pool-under-75k": "Pools under $75k",
                               "pool-under-150k": "Pools under $150k"}
ALL_BANDS: frozenset[str] = frozenset(BANDS) | frozenset(POOL_BANDS)
#: At most this many wallets on the same band may buy one coin (in an hour),
#: so one bad coin cannot catch a whole group.
MAX_SAME_BAND_PER_COIN = 2


def is_pool_band(band: str) -> bool:
    return band in POOL_BANDS


def in_pool_band(band: str, pool_usd: Decimal | None) -> bool:
    """Whether a coin whose pool holds `pool_usd` may be bought on a pool
    band. An unknown pool size is a no, as an unknown market cap is."""
    return band in POOL_BANDS and pool_usd is not None and pool_usd < POOL_BANDS[band]


def in_band(band: str, fdv: Decimal | None) -> bool:
    """Whether a coin of market cap `fdv` may be bought on `band`. An unknown
    band, or an unknown market cap on a bounded band, is a no."""
    if band not in BANDS:
        return False
    lo, hi = BANDS[band]
    if lo is None and hi is None:
        return True
    if fdv is None:
        return False
    return (lo is None or fdv >= lo) and (hi is None or fdv < hi)


#: Family investment (Karthik, 2026-09-28): USER 1-7 sit behind a password
#: of their own (`REAL_WALLET_INVESTMENT_PASSWORD_HASH`); USER 8-10 and the
#: fees stay behind the users password. No user wallet is open to the admin
#: sign-in alone any more.
INVESTMENT_MEMBERS: frozenset[str] = frozenset(f"USER{i}" for i in range(1, 8))
TOKEN_HOURS = 12
_PBKDF2_ROUNDS = 600_000


def scope(member: str) -> str:
    """Which password opens this wallet: "investment" or "users"."""
    return "investment" if member in INVESTMENT_MEMBERS else "users"


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


def password_scope(password: str) -> str | None:
    """The lock this password opens, or None. Each hash unset = that lock shut."""
    if password_ok(password, settings.REAL_WALLET_INVESTMENT_PASSWORD_HASH):
        return "investment"
    if password_ok(password, settings.REAL_WALLET_USERS_PASSWORD_HASH):
        return "users"
    return None


def issue_token(scopes: frozenset[str] | set[str] = frozenset({"users"}), *,
                now: datetime | None = None) -> tuple[str, datetime]:
    """One token for every lock this tab has opened (`scopes`)."""
    now = now or datetime.now(UTC)
    expires = now + timedelta(hours=TOKEN_HOURS)
    token = jwt.encode({"type": "users", "sub": "users", "scopes": sorted(scopes),
                        "iat": int(now.timestamp()),
                        "exp": int(expires.timestamp()), "iss": settings.PROJECT_NAME},
                       settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires


def token_scopes(token: str | None) -> frozenset[str]:
    """The locks a token opens; none for a bad, expired or missing one. A token
    from before the family-investment lock carries no scopes and was issued
    for the users password."""
    if not isinstance(token, str) or not token:
        return frozenset()
    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
                            issuer=settings.PROJECT_NAME,
                            options={"require": ["exp", "iat", "sub"]})
    except jwt.InvalidTokenError:
        return frozenset()
    if claims.get("type") != "users":
        return frozenset()
    scopes = claims.get("scopes", ["users"])
    return frozenset(s for s in scopes if s in ("investment", "users")) \
        if isinstance(scopes, list) else frozenset()


def opens(member: str, token: str | None) -> bool:
    return scope(member) in token_scopes(token)


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


def device_ok(key: str | None, allowed: str | None = None) -> bool:
    """Whether a browser's device key is one of Karthik's (Karthik, 2026-10-01:
    "this jupiter box should only visible to my macbook"). The server keeps
    only sha256 digests; the key itself lives in his browsers."""
    if not isinstance(key, str) or len(key) < 32:
        return False
    digest = hashlib.sha256(key.encode()).hexdigest()
    known = (settings.REAL_WALLET_JUPITER_DEVICES if allowed is None else allowed)
    return any(hmac.compare_digest(digest, d.strip().lower())
               for d in known.split(",") if d.strip())


def label(member: str) -> str:
    """"USER7" -> "USER 7", for people to read."""
    return member.replace("USER", "USER ", 1)

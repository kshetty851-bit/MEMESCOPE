"""Family shares of the one real wallet: sizing, balances and the password.

## How a trade is shared

The wallet places ONE order per coin, exactly as before. Its size is the
owner's own ticket plus the ticket of every family member who is switched on
and has the money for it. Each person owns their dollars of that order, and a
closed trade's realised result is split in the same proportion.

Every member follows the same arm the owner nominated, so every member is
buying the same coin at the same second. Their sizes therefore ADD UP in the
pool, and on this arm the edge is gone above about $400 a coin (measured
2026-09-24 on BASE_75k_quiet_5m's 249 trades: +0.53% a trade at $400, -0.10%
at $800). `COMBINED_CAP_USD` holds the whole order under that line by scaling
every share down together, so nobody's slice is sacrificed for anybody else's.

## With nobody switched on, nothing changes

`split` returns the owner's ticket untouched when no member takes part. The
driver's order is then byte-for-byte what it was before this module existed;
`tests/unit/test_real_wallet_family.py` pins that.

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
import uuid
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.real_wallet_execution import RealWalletLiveIntent, RealWalletPosition
from app.models.real_wallet_family import (
    RealWalletFamilyAllocation,
    RealWalletFamilyLedger,
    RealWalletFamilyMember,
)

MEMBERS: tuple[str, ...] = ("JAYA", "ASHA", "APOORVA")
TICKETS_USD: tuple[Decimal, ...] = tuple(
    Decimal(t) for t in ("10", "20", "25", "50", "100", "200"))
#: The most one coin may carry across the owner and every member together.
COMBINED_CAP_USD = Decimal("400")
TOKEN_HOURS = 12
_CENT = Decimal("0.01")
_PBKDF2_ROUNDS = 600_000


# --- sizing -----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Seat:
    """One member as sizing sees them."""
    name: str
    enabled: bool
    ticket: Decimal
    available: Decimal


@dataclass(frozen=True, slots=True)
class Split:
    """One order and who owns which dollars of it."""
    total: Decimal
    owner: Decimal
    members: dict[str, Decimal]


def split(own: Decimal, seats: Iterable[Seat], *,
          cap: Decimal = COMBINED_CAP_USD) -> Split:
    """The order for one coin: the owner's ticket plus each member who is on
    and can pay for a whole ticket, scaled down together if it would exceed
    `cap`."""
    taking = {s.name: s.ticket for s in seats
              if s.enabled and s.ticket > 0 and s.available >= s.ticket}
    total = own + sum(taking.values(), Decimal(0))
    if not taking or total <= 0:
        return Split(total=own, owner=own, members={})
    if total > cap:
        return scale(Split(total=total, owner=own, members=taking), cap)
    return Split(total=total, owner=own, members=taking)


def scale(order: Split, to: Decimal) -> Split:
    """The same shares on a smaller order. Members are rounded DOWN to the
    cent and the owner takes the remainder, so the parts always sum to `to`
    exactly and no member is ever charged more than their share."""
    if order.total <= 0 or to >= order.total:
        return order
    k = to / order.total
    members = {n: (v * k).quantize(_CENT, rounding=ROUND_DOWN)
               for n, v in order.members.items()}
    return Split(total=to, owner=to - sum(members.values(), Decimal(0)), members=members)


# --- balances ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Share:
    """One member's dollars inside one order, and how that order ended."""
    amount: Decimal
    order_total: Decimal
    state: str                  # open | closed | void
    pnl_total: Decimal | None   # the position's realised result, when closed


@dataclass(frozen=True, slots=True)
class Balance:
    deposited: Decimal
    withdrawn: Decimal
    pnl: Decimal        # realised, on closed trades
    in_trades: Decimal  # dollars sitting in trades not yet closed
    trades: int
    wins: int

    @property
    def balance(self) -> Decimal:
        """What the member owns: in trades or not."""
        return self.deposited - self.withdrawn + self.pnl

    @property
    def available(self) -> Decimal:
        """What the member can put into the next trade."""
        return self.balance - self.in_trades


def balance(ledger: Iterable[tuple[str, Decimal]], shares: Iterable[Share]) -> Balance:
    deposited = withdrawn = pnl = in_trades = Decimal(0)
    trades = wins = 0
    for kind, amount in ledger:
        if kind == "deposit":
            deposited += amount
        elif kind == "withdrawal":
            withdrawn += amount
    for s in shares:
        if s.state == "open":
            in_trades += s.amount
        elif s.state == "closed" and s.pnl_total is not None and s.order_total > 0:
            mine = (s.pnl_total * s.amount / s.order_total).quantize(_CENT)
            pnl += mine
            trades += 1
            wins += 1 if mine > 0 else 0
    return Balance(deposited, withdrawn, pnl, in_trades, trades, wins)


def share_state(intent_state: str, position_status: str | None) -> str:
    """How one order stands, for accounting."""
    if position_status == "CLOSED":
        return "closed"
    if position_status is None and intent_state in ("failed", "blocked"):
        return "void"       # no money ever moved
    return "open"


# --- the database -----------------------------------------------------------

async def shares_by_member(session: AsyncSession) -> dict[str, list[tuple[Share, dict]]]:
    """Every allocation, with its order's outcome, grouped by member."""
    rows = (await session.execute(
        select(RealWalletFamilyAllocation.member, RealWalletFamilyAllocation.amount_usd,
               RealWalletLiveIntent.requested_usd, RealWalletLiveIntent.state,
               RealWalletLiveIntent.mint_address, RealWalletLiveIntent.created_at,
               RealWalletPosition.status, RealWalletPosition.realised_net_pnl_usd,
               RealWalletPosition.closed_at)
        .join(RealWalletLiveIntent,
              RealWalletLiveIntent.id == RealWalletFamilyAllocation.intent_id)
        .outerjoin(RealWalletPosition,
                   RealWalletPosition.opened_live_intent_id == RealWalletLiveIntent.id)
        .order_by(RealWalletLiveIntent.created_at.desc()))).all()
    out: dict[str, list[tuple[Share, dict]]] = defaultdict(list)
    for (member, amount, total, state, mint, created, status, pnl, closed) in rows:
        share = Share(amount=amount, order_total=total or Decimal(0),
                      state=share_state(state, status), pnl_total=pnl)
        out[member].append((share, {"mint": mint, "bought_at": created,
                                    "sold_at": closed}))
    return out


async def ledger_by_member(session: AsyncSession) -> dict[str, list[RealWalletFamilyLedger]]:
    rows = (await session.execute(
        select(RealWalletFamilyLedger).order_by(RealWalletFamilyLedger.at.desc()))).scalars()
    out: dict[str, list[RealWalletFamilyLedger]] = defaultdict(list)
    for r in rows:
        out[r.member].append(r)
    return out


async def seats(session: AsyncSession) -> list[Seat]:
    """Every member as the next order would see them."""
    members = (await session.execute(select(RealWalletFamilyMember))).scalars().all()
    if not members:
        return []
    shares = await shares_by_member(session)
    ledgers = await ledger_by_member(session)
    out = []
    for m in members:
        b = balance(((r.kind, r.amount_usd) for r in ledgers.get(m.name, ())),
                    (s for s, _ in shares.get(m.name, ())))
        out.append(Seat(m.name, m.enabled, m.ticket_usd, b.available))
    return out


def record(session: AsyncSession, intent_id: uuid.UUID, order: Split) -> None:
    """Write each member's share of an order, in the caller's transaction."""
    for name, amount in order.members.items():
        if amount > 0:
            session.add(RealWalletFamilyAllocation(
                intent_id=intent_id, member=name, amount_usd=amount))


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


def rows_for_page(items: Sequence[tuple[Share, dict]]) -> list[dict]:
    """A member's trades, newest first, with their own dollars and result."""
    out = []
    for share, meta in items:
        mine = None
        if share.state == "closed" and share.pnl_total is not None and share.order_total > 0:
            mine = (share.pnl_total * share.amount / share.order_total).quantize(_CENT)
        out.append({**meta, "amount_usd": share.amount, "order_usd": share.order_total,
                    "state": share.state, "pnl_usd": mine,
                    "pct": (None if mine is None or not share.amount
                            else (100 * mine / share.amount).quantize(_CENT))})
    return out

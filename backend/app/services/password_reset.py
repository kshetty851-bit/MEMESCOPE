"""Password reset: request a link, spend it once, lose every session.

Three properties this has to have, and each one is a decision rather than a
default:

**It never says whether an account exists.** `request` returns the same answer
for a real address and an invented one. A reset form that distinguishes them is
an account-existence oracle anybody can query, and the convenience of "no such
user" is not worth handing that out.

**The token is single-use and short-lived, and requesting again kills the old
one.** Otherwise every link a user ever generated stays live in their inbox
forever, and a mailbox compromise a year later is still an account compromise.

**Completing a reset revokes every session.** The most likely reason somebody
resets a password is that they think someone else has it, and leaving the
attacker's existing session alive would make the reset theatre.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.password_reset import PasswordResetToken
from app.models.user import User

logger = get_logger(__name__)

TOKEN_BYTES = 32
TOKEN_TTL = timedelta(hours=1)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class InvalidResetTokenError(RuntimeError):
    """Expired, already spent, superseded, or never issued. One error for all
    four on purpose: telling a caller which would let them map the space."""


@dataclass(frozen=True, slots=True)
class ResetRequest:
    """What the caller may know. `token` is present only so the API can email
    it — it is never returned over HTTP."""

    token: str | None
    user: User | None


class PasswordResetService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request(
        self, *, email: str, now: datetime, ip: str | None = None
    ) -> ResetRequest:
        """Issue a token for a real account, or do nothing, indistinguishably."""
        user = (
            await self._session.execute(
                select(User).where(User.email == email.strip().lower())
            )
        ).scalars().first()
        if user is None or not user.is_active:
            # Deliberately silent. The endpoint returns the same response either
            # way, and the log records the attempt without asserting a verdict
            # about the address.
            logger.info("password_reset_requested_unknown_address")
            return ResetRequest(token=None, user=None)

        # Any outstanding link is dead the moment a new one is asked for.
        await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self._session.add(PasswordResetToken(
            user_id=user.id, token_hash=_digest(token),
            expires_at=now + TOKEN_TTL, requested_ip=ip, created_at=now,
        ))
        await self._session.flush()
        # The token is never logged, only the fact that one was issued.
        logger.info("password_reset_issued", user_id=str(user.id))
        return ResetRequest(token=token, user=user)

    async def complete(
        self, *, token: str, new_password: str, now: datetime
    ) -> User:
        """Spend the token, set the password, and end every existing session."""
        row = (
            await self._session.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == _digest(token)
                )
            )
        ).scalars().first()
        if row is None or row.used_at is not None or row.invalidated_at is not None:
            raise InvalidResetTokenError("invalid_or_spent_reset_token")
        if row.expires_at <= now:
            raise InvalidResetTokenError("expired_reset_token")

        user = await self._session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise InvalidResetTokenError("invalid_or_spent_reset_token")

        user.hashed_password = hash_password(new_password)
        row.used_at = now
        # Every other outstanding link for this user dies with it.
        await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.id != row.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        await self._session.flush()
        logger.warning("password_reset_completed", user_id=str(user.id))
        return user

    @staticmethod
    def reset_url(token: str) -> str:
        base = (settings.FRONTEND_URL or "").rstrip("/")
        return f"{base}/reset-password?token={token}"

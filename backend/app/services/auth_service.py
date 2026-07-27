"""Authentication use cases: register, login, refresh rotation, logout."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.schemas.user import UserCreate

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClientContext:
    """Where a session was created from — recorded for audit and revocation UX."""

    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user: User
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)

    # --- Registration -------------------------------------------------------

    async def register(self, payload: UserCreate, ctx: ClientContext) -> IssuedSession:
        email = payload.email.strip().lower()
        if await self.users.email_exists(email):
            raise ConflictError("An account with that email already exists.")

        user = await self.users.create(
            email=email,
            hashed_password=hash_password(payload.password),
            display_name=payload.display_name,
        )
        logger.info("user_registered", user_id=str(user.id))
        return await self._issue_session(user, ctx)

    # --- Login --------------------------------------------------------------

    async def authenticate(
        self, email: str, password: str, ctx: ClientContext
    ) -> IssuedSession:
        user = await self.users.get_by_email(email)

        # Hash even when the user is missing, so response time does not reveal
        # whether an email is registered.
        password_ok = (
            verify_password(password, user.hashed_password)
            if user
            else verify_password(password, _DUMMY_HASH)
        )
        if user is None or not password_ok:
            raise AuthenticationError("Incorrect email or password.")
        if not user.is_active:
            raise PermissionDeniedError("This account has been disabled.")

        await self.users.touch_last_login(user.id)
        logger.info("user_login", user_id=str(user.id))
        return await self._issue_session(user, ctx)

    # --- Refresh rotation ---------------------------------------------------

    async def refresh(self, presented_token: str, ctx: ClientContext) -> IssuedSession:
        token_hash = hash_refresh_token(presented_token)
        stored = await self.refresh_tokens.get_by_hash(token_hash)

        if stored is None:
            raise AuthenticationError("Refresh token is invalid.")

        if stored.revoked_at is not None:
            # A revoked token being presented means it was captured after
            # rotation. Kill every session for that user and force a re-login.
            await self.refresh_tokens.revoke_all_for_user(stored.user_id)
            logger.warning("refresh_token_reuse_detected", user_id=str(stored.user_id))
            raise AuthenticationError(
                "Refresh token was already used. All sessions have been revoked.",
                code="token_reuse_detected",
            )

        if stored.is_expired:
            raise AuthenticationError("Refresh token has expired.", code="token_expired")

        user = stored.user
        if not user.is_active:
            raise PermissionDeniedError("This account has been disabled.")

        issued = await self._issue_session(user, ctx)
        rotated = await self.refresh_tokens.get_by_hash(
            hash_refresh_token(issued.refresh_token)
        )
        await self.refresh_tokens.revoke(stored, replaced_by=rotated)
        return issued

    # --- Logout -------------------------------------------------------------

    async def logout(self, presented_token: str | None) -> None:
        if not presented_token:
            return
        stored = await self.refresh_tokens.get_by_hash(hash_refresh_token(presented_token))
        if stored is not None and stored.revoked_at is None:
            await self.refresh_tokens.revoke(stored)
            logger.info("user_logout", user_id=str(stored.user_id))

    async def logout_all(self, user_id: uuid.UUID) -> int:
        revoked = await self.refresh_tokens.revoke_all_for_user(user_id)
        logger.info("user_logout_all", user_id=str(user_id), revoked=revoked)
        return revoked

    # --- Internals ----------------------------------------------------------

    async def _issue_session(self, user: User, ctx: ClientContext) -> IssuedSession:
        access_token, payload = create_access_token(user.id, scopes=[user.role.value])
        plaintext, digest, expires_at = create_refresh_token()

        self.refresh_tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=digest,
                expires_at=expires_at,
                user_agent=ctx.user_agent,
                ip_address=ctx.ip_address,
            )
        )
        await self.session.flush()

        return IssuedSession(
            user=user,
            access_token=access_token,
            refresh_token=plaintext,
            expires_in=int((payload.expires_at - datetime.now(UTC)).total_seconds()),
        )


# Fixed hash of a random value, used purely to equalise timing on unknown emails.
_DUMMY_HASH = hash_password("memescope-timing-equaliser-" + settings.PROJECT_NAME)

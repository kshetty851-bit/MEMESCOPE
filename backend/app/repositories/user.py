"""User and refresh-token persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update

from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return (await self.session.execute(stmt)).scalars().first()

    async def email_exists(self, email: str) -> bool:
        return await self.get_by_email(email) is not None

    async def touch_last_login(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(last_login_at=datetime.now(UTC))
        )


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalars().first()

    async def revoke(
        self, token: RefreshToken, *, replaced_by: RefreshToken | None = None
    ) -> None:
        token.revoked_at = datetime.now(UTC)
        if replaced_by is not None:
            token.replaced_by_id = replaced_by.id
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Used on logout-everywhere and on refresh-token reuse detection."""
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            ),
        )
        return int(result.rowcount or 0)

    async def purge_expired(self) -> int:
        return await self.delete_by_expiry(datetime.now(UTC))

    async def delete_by_expiry(self, before: datetime) -> int:
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < before)
            ),
        )
        return int(result.rowcount or 0)

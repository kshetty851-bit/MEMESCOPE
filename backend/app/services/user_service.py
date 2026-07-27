"""User profile use cases."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.schemas.user import PasswordChange, UserUpdate


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    async def update_profile(self, user: User, payload: UserUpdate) -> User:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def change_password(self, user: User, payload: PasswordChange) -> None:
        if not verify_password(payload.current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect.")
        user.hashed_password = hash_password(payload.new_password)
        # A password change invalidates every existing session.
        await self.refresh_tokens.revoke_all_for_user(user.id)
        await self.session.flush()

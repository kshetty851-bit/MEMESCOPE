"""Shared FastAPI dependencies: current user, role gates, service wiring."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.redis import is_token_denied
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.services.auth_service import AuthService, ClientContext
from app.services.user_service import UserService

# auto_error=False so a missing header raises our own envelope, not FastAPI's.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

#: Stable identity for the development bypass principal. A fixed, obviously
#: synthetic UUID so it is recognisable in logs and cannot collide with a real
#: account, which are generated randomly.
DEVELOPMENT_USER_ID = uuid.UUID("00000000-0000-4000-8000-00000000d0e5")

DbSession = Annotated[AsyncSession, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def _developer_principal() -> User:
    """The identity every request carries while the bypass is active.

    Deliberately **not** persisted and never written to the database: it exists
    for the lifetime of one request. A real row would outlive the flag, leaving
    a privileged account behind in whatever database the developer happened to
    be pointed at.

    The id is fixed so logs and any per-user state stay coherent across requests
    within a session.
    """
    # `created_at` and `updated_at` are set explicitly: they are server defaults,
    # and this object is never flushed, so nothing would populate them and the
    # response schema would fail to serialise a null.
    now = datetime.now(UTC)
    return User(
        id=DEVELOPMENT_USER_ID,
        email=settings.DEVELOPMENT_USER_EMAIL,
        hashed_password="",
        display_name="Developer",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
        created_at=now,
        updated_at=now,
    )


async def get_current_user(
    request: Request, session: DbSession, credentials: Credentials
) -> User:
    # Development bypass. `auth_bypass_active` is already anded with the
    # environment, so this branch is unreachable outside local development, and
    # the production config refuses to boot if the flag is set at all.
    if settings.auth_bypass_active:
        developer = _developer_principal()
        request.state.user_id = str(developer.id)
        return developer

    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token.")

    payload = decode_access_token(credentials.credentials)

    if await is_token_denied(payload.jti):
        raise AuthenticationError("Token has been revoked.", code="token_revoked")

    try:
        user_id = uuid.UUID(payload.subject)
    except ValueError as exc:
        raise AuthenticationError("Token subject is malformed.") from exc

    user = await UserRepository(session).get(user_id)
    if user is None:
        raise AuthenticationError("Account no longer exists.")
    if not user.is_active:
        raise PermissionDeniedError("This account has been disabled.")

    # Stash the claims: logout needs the jti and remaining TTL to deny the token.
    request.state.token_jti = payload.jti
    request.state.token_expires_at = payload.expires_at
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(
    *roles: UserRole,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    """Dependency factory gating a route behind one or more roles."""

    async def _guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError(
                "This endpoint requires one of: " + ", ".join(r.value for r in roles)
            )
        return user

    return _guard


AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]


def get_client_context(request: Request) -> ClientContext:
    return ClientContext(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


def get_auth_service(session: DbSession) -> AuthService:
    return AuthService(session)


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
ClientContextDep = Annotated[ClientContext, Depends(get_client_context)]

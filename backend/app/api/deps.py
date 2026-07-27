"""Shared FastAPI dependencies: current user, role gates, service wiring."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

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

DbSession = Annotated[AsyncSession, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


async def get_current_user(
    request: Request, session: DbSession, credentials: Credentials
) -> User:
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

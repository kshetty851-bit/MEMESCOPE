"""Authentication routes.

Token strategy: the access token is returned in the response body (the SPA keeps
it in memory), while the refresh token is set as an httpOnly, SameSite cookie
scoped to `/api/v1/auth` so it is never readable by JavaScript and never sent
to ordinary API routes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AuthServiceDep, ClientContextDep, CurrentUser
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.redis import deny_token
from app.schemas.auth import AuthResponse, LoginRequest, MessageResponse
from app.schemas.user import UserCreate, UserRead
from app.services.auth_service import IssuedSession

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def _to_response(session: IssuedSession, response: Response) -> AuthResponse:
    _set_refresh_cookie(response, session.refresh_token)
    return AuthResponse(
        access_token=session.access_token,
        expires_in=session.expires_in,
        user=UserRead.model_validate(session.user),
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and start a session",
)
async def register(
    payload: UserCreate,
    response: Response,
    service: AuthServiceDep,
    ctx: ClientContextDep,
) -> AuthResponse:
    return _to_response(await service.register(payload, ctx), response)


@router.post("/login", response_model=AuthResponse, summary="Exchange credentials for tokens")
async def login(
    payload: LoginRequest,
    response: Response,
    service: AuthServiceDep,
    ctx: ClientContextDep,
) -> AuthResponse:
    session = await service.authenticate(payload.email, payload.password, ctx)
    return _to_response(session, response)


@router.post("/refresh", response_model=AuthResponse, summary="Rotate the refresh token")
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    ctx: ClientContextDep,
) -> AuthResponse:
    presented = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not presented:
        raise AuthenticationError("No refresh token was provided.")
    return _to_response(await service.refresh(presented, ctx), response)


@router.post("/logout", response_model=MessageResponse, summary="End the current session")
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> MessageResponse:
    await service.logout(request.cookies.get(settings.REFRESH_COOKIE_NAME))
    _clear_refresh_cookie(response)
    return MessageResponse(message="Signed out.")


@router.post(
    "/logout-all",
    response_model=MessageResponse,
    summary="Revoke every session for the current user",
)
async def logout_all(
    request: Request,
    response: Response,
    user: CurrentUser,
    service: AuthServiceDep,
) -> MessageResponse:
    await service.logout_all(user.id)

    # Also deny the access token that made this call, for its remaining life.
    jti = getattr(request.state, "token_jti", None)
    expires_at = getattr(request.state, "token_expires_at", None)
    if jti and expires_at:
        await deny_token(jti, int((expires_at - datetime.now(UTC)).total_seconds()))

    _clear_refresh_cookie(response)
    return MessageResponse(message="All sessions revoked.")

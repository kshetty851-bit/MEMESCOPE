"""Authentication routes.

Token strategy: the access token is returned in the response body (the SPA keeps
it in memory), while the refresh token is set as an httpOnly, SameSite cookie
scoped to `/api/v1/auth` so it is never readable by JavaScript and never sent
to ordinary API routes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import AuthServiceDep, ClientContextDep, CurrentUser, DbSession
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger
from app.core.redis import deny_token
from app.reports.email import provider_from_settings
from app.services.password_reset import InvalidResetTokenError, PasswordResetService
from app.services.password_reset_email import build as reset_email
from app.schemas.auth import AuthResponse, LoginRequest, MessageResponse
from app.schemas.user import UserCreate, UserRead
from app.services.auth_service import IssuedSession

logger = get_logger(__name__)

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


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetCompleteIn(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    summary="Send a password-reset link, if that address has an account",
)
async def request_password_reset(
    payload: PasswordResetRequestIn,
    request: Request,
    session: DbSession,
) -> MessageResponse:
    """Always the same answer, whether or not the address exists.

    A reset form that distinguishes them is an account-existence oracle anybody
    can query, and "no such user" is not worth handing that out.
    """
    service = PasswordResetService(session)
    issued = await service.request(
        email=payload.email, now=datetime.now(UTC),
        ip=(request.client.host if request.client else None),
    )
    if issued.token and issued.user:
        try:
            await asyncio.to_thread(
                provider_from_settings().send,
                reset_email(
                    recipient=issued.user.email,
                    reset_url=PasswordResetService.reset_url(issued.token),
                ),
            )
        except Exception:  # pragma: no cover - delivery failure must not leak
            # A send failure must not change the response, or the timing of it
            # would answer the question the response refuses to.
            logger.warning("password_reset_email_send_failed")
    await session.commit()
    return MessageResponse(
        message="If that address has an account, a reset link is on its way."
    )


@router.post(
    "/password-reset/complete",
    response_model=MessageResponse,
    summary="Spend a reset token and set a new password",
)
async def complete_password_reset(
    payload: PasswordResetCompleteIn,
    session: DbSession,
    service: AuthServiceDep,
) -> MessageResponse:
    """Set the password, then end every existing session.

    Somebody resetting a password usually believes another party has it.
    Leaving that party's session alive would make the reset theatre.
    """
    try:
        user = await PasswordResetService(session).complete(
            token=payload.token, new_password=payload.new_password,
            now=datetime.now(UTC),
        )
    except InvalidResetTokenError as exc:
        await session.rollback()
        raise AuthenticationError(
            "That reset link is no longer valid. Request a new one.",
            code="invalid_reset_token",
        ) from exc
    await service.logout_all(user.id)
    await session.commit()
    return MessageResponse(message="Password updated. Sign in with your new password.")


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

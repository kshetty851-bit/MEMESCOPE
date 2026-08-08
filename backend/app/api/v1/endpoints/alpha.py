"""Temporary private-alpha access gate.

This is deliberately smaller than user authentication: one server-side code,
one httpOnly session cookie, and no account identity. It exists only until the
real authentication product decision replaces it.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Request, Response, status

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import create_alpha_access_token, decode_alpha_access_token
from app.schemas.alpha import AlphaSessionStatus, AlphaUnlockRequest
from app.schemas.auth import MessageResponse

router = APIRouter(prefix="/alpha", tags=["alpha"])


def _set_alpha_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.ALPHA_ACCESS_COOKIE_NAME,
        value=token,
        max_age=settings.ALPHA_ACCESS_SESSION_DAYS * 24 * 3600,
        path=settings.ALPHA_ACCESS_COOKIE_PATH,
        domain=settings.ALPHA_ACCESS_COOKIE_DOMAIN,
        secure=settings.ALPHA_ACCESS_COOKIE_SECURE,
        httponly=True,
        samesite=settings.ALPHA_ACCESS_COOKIE_SAMESITE,
    )


def _clear_alpha_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.ALPHA_ACCESS_COOKIE_NAME,
        path=settings.ALPHA_ACCESS_COOKIE_PATH,
        domain=settings.ALPHA_ACCESS_COOKIE_DOMAIN,
        secure=settings.ALPHA_ACCESS_COOKIE_SECURE,
        httponly=True,
        samesite=settings.ALPHA_ACCESS_COOKIE_SAMESITE,
    )


def _read_alpha_session(request: Request) -> AlphaSessionStatus:
    token = request.cookies.get(settings.ALPHA_ACCESS_COOKIE_NAME)
    if not token:
        return AlphaSessionStatus(authenticated=False)

    try:
        payload = decode_alpha_access_token(token)
    except AuthenticationError:
        return AlphaSessionStatus(authenticated=False)

    return AlphaSessionStatus(authenticated=True, expires_at=payload.expires_at)


@router.get(
    "/session",
    response_model=AlphaSessionStatus,
    summary="Check the temporary alpha-access session",
)
async def session(request: Request) -> AlphaSessionStatus:
    return _read_alpha_session(request)


@router.post(
    "/unlock",
    response_model=AlphaSessionStatus,
    status_code=status.HTTP_201_CREATED,
    summary="Validate the private-alpha access code",
)
async def unlock(payload: AlphaUnlockRequest, response: Response) -> AlphaSessionStatus:
    expected = settings.ALPHA_ACCESS_CODE.get_secret_value()
    if not secrets.compare_digest(payload.code.strip(), expected):
        raise AuthenticationError(
            "Access code not recognised.",
            code="alpha_access_denied",
        )

    token, claims = create_alpha_access_token()
    _set_alpha_cookie(response, token)
    return AlphaSessionStatus(authenticated=True, expires_at=claims.expires_at)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Clear the temporary alpha-access session",
)
async def logout(response: Response) -> MessageResponse:
    _clear_alpha_cookie(response)
    return MessageResponse(message="Alpha access cleared.")

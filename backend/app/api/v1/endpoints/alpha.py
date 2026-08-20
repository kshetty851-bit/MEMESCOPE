"""Temporary private-alpha access gate.

This is deliberately smaller than user authentication: one server-side code,
one httpOnly session cookie, and no account identity. It exists only until the
real authentication product decision replaces it.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import create_alpha_access_token, decode_alpha_access_token
from app.schemas.alpha import (
    AlphaActivityOverview,
    AlphaActivityRequest,
    AlphaSessionStatus,
    AlphaUnlockRequest,
)
from app.schemas.auth import MessageResponse
from app.services.alpha_activity import AlphaActivityService

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
    if settings.alpha_gate_open:
        # No gate is configured, so every visitor already has access — and the
        # rest of the API already behaves that way, answering every request
        # without a cookie. Saying `authenticated: false` here made the two
        # halves disagree about the same setting: the API was wide open while
        # the dashboard bounced every visitor to the landing page.
        #
        # `alpha_gate_open` ands the flag with `ENVIRONMENT == "local"`, so
        # this cannot fire in production or under test. Production also refuses
        # to boot with the gate off, so there are two independent reasons this
        # branch is unreachable where it would matter.
        #
        # No expiry is reported: there is no session to expire.
        return AlphaSessionStatus(authenticated=True)

    token = request.cookies.get(settings.ALPHA_ACCESS_COOKIE_NAME)
    if not token:
        return AlphaSessionStatus(authenticated=False)

    try:
        payload = decode_alpha_access_token(token)
    except AuthenticationError:
        return AlphaSessionStatus(authenticated=False)

    return AlphaSessionStatus(authenticated=True, expires_at=payload.expires_at)


def _alpha_jti(request: Request) -> str:
    token = request.cookies.get(settings.ALPHA_ACCESS_COOKIE_NAME)
    if not token:
        raise AuthenticationError("Alpha access is required.", code="alpha_access_required")
    return decode_alpha_access_token(token).jti


def _safe_path(path: str) -> str:
    # Route only: query/hash must never become session telemetry.
    return "/" + path.split("?", 1)[0].split("#", 1)[0].lstrip("/")


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
async def unlock(
    payload: AlphaUnlockRequest, response: Response, session: DbSession
) -> AlphaSessionStatus:
    expected = settings.ALPHA_ACCESS_CODE.get_secret_value()
    if not secrets.compare_digest(payload.code.strip(), expected):
        raise AuthenticationError(
            "Access code not recognised.",
            code="alpha_access_denied",
        )

    token, claims = create_alpha_access_token()
    _set_alpha_cookie(response, token)
    now = datetime.now(UTC)
    await AlphaActivityService(session).unlock(claims.jti, now=now)
    return AlphaSessionStatus(authenticated=True, expires_at=claims.expires_at)


@router.post(
    "/activity",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record minimal alpha activity",
)
async def activity(
    payload: AlphaActivityRequest, request: Request, session: DbSession
) -> Response:
    await AlphaActivityService(session).heartbeat(
        _alpha_jti(request), _safe_path(payload.path), now=datetime.now(UTC)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/activity", response_model=AlphaActivityOverview, summary="Read private-alpha activity"
)
async def activity_overview(_admin: AdminUser, session: DbSession) -> AlphaActivityOverview:
    return await AlphaActivityService(session).overview(now=datetime.now(UTC))


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Clear the temporary alpha-access session",
)
async def logout(response: Response) -> MessageResponse:
    _clear_alpha_cookie(response)
    return MessageResponse(message="Alpha access cleared.")

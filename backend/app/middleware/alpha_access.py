"""Temporary private-alpha API gate."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import decode_alpha_access_token

EXEMPT_EXACT_PATHS = frozenset(
    {
        "/live",
        "/ready",
        "/api/v1/health",
        "/api/v1/health/pipeline",
    }
)

EXEMPT_PREFIXES = (
    "/api/v1/alpha",
    "/api/v1/auth",
)


class AlphaAccessMiddleware(BaseHTTPMiddleware):
    """Require the server-issued alpha cookie for private production API reads."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            not settings.ALPHA_ACCESS_REQUIRED
            or request.method == "OPTIONS"
            or self._is_exempt(request.url.path)
        ):
            return await call_next(request)

        token = request.cookies.get(settings.ALPHA_ACCESS_COOKIE_NAME)
        if token:
            try:
                decode_alpha_access_token(token)
                return await call_next(request)
            except AuthenticationError:
                pass

        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "alpha_access_required",
                    "message": "Alpha access is required.",
                    "details": {},
                },
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @staticmethod
    def _is_exempt(path: str) -> bool:
        return path in EXEMPT_EXACT_PATHS or any(
            path.startswith(prefix) for prefix in EXEMPT_PREFIXES
        )

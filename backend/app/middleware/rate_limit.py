"""Redis-backed fixed-window rate limiting.

Keyed by bearer token when present, otherwise by client IP, so a shared NAT does
not throttle authenticated users against each other. Health probes are exempt.
"""

from __future__ import annotations

import hashlib

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.logging import get_logger
from app.core.redis import check_rate_limit

logger = get_logger(__name__)

EXEMPT_PATHS = frozenset({"/live", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, limit: int, window_seconds: int) -> None:
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._is_exempt(request.url.path):
            return await call_next(request)

        identifier = self._identify(request)
        try:
            allowed, remaining, retry_after = await check_rate_limit(
                identifier, limit=self.limit, window_seconds=self.window_seconds
            )
        except Exception:
            # Redis being down must not take the API down with it.
            logger.warning("rate_limit_backend_unavailable", exc_info=True)
            return await call_next(request)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests. Please slow down.",
                        "details": {"retry_after_seconds": retry_after},
                    },
                    "request_id": getattr(request.state, "request_id", None),
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    @staticmethod
    def _is_exempt(path: str) -> bool:
        return any(path.endswith(exempt) for exempt in EXEMPT_PATHS)

    @staticmethod
    def _identify(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return "tok:" + hashlib.sha256(auth[7:].encode()).hexdigest()[:32]
        client = request.client.host if request.client else "unknown"
        return f"ip:{client}"

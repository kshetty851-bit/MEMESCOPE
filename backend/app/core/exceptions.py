"""Application exception hierarchy and the handlers that render it.

Every error the API returns has the same JSON envelope:

    {"error": {"code": "not_found", "message": "...", "details": {...}},
     "request_id": "..."}

so clients can branch on a stable machine-readable `code` instead of parsing prose.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for all expected, domain-level failures."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource already exists."


class ValidationError(AppError):
    # Literal 422: Starlette renamed this constant, and the literal works
    # across both versions.
    status_code = 422
    code = "validation_error"
    message = "Request payload failed validation."


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "authentication_error"
    message = "Authentication credentials are missing or invalid."


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "You do not have permission to perform this action."


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests. Please slow down."


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "A dependency is unavailable."


def _envelope(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details or {}},
        "request_id": getattr(request.state, "request_id", None),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error",
            code=exc.code,
            status_code=exc.status_code,
            path=request.url.path,
            detail=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                request, code=exc.code, message=exc.message, details=exc.details
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = {
            401: "authentication_error",
            403: "permission_denied",
            404: "not_found",
            405: "method_not_allowed",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code=code, message=str(exc.detail)),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                request,
                code="validation_error",
                message="Request payload failed validation.",
                # jsonable: pydantic v2 errors can carry non-serialisable ctx values.
                details={"errors": _clean_errors(exc.errors())},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                request,
                code="internal_error",
                message="An unexpected error occurred.",
            ),
        )


def _clean_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for err in errors:
        cleaned.append(
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    return cleaned

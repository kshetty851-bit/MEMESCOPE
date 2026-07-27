"""MemeScope AI — FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, init_redis
from app.db.session import dispose_engine
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    configure_logging()
    logger.info(
        "application_starting",
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
    )
    await init_redis()
    try:
        yield
    finally:
        await close_redis()
        await dispose_engine()
        logger.info("application_stopped")


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "AI-powered Solana meme coin discovery platform. "
            "This is the Day 1 platform foundation: auth, health, and plumbing."
        ),
        openapi_url=None if settings.is_production else "/openapi.json",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        lifespan=lifespan,
    )

    # Middleware runs bottom-up on the way in: request context is added last so
    # it wraps everything and every log line downstream carries the request id.
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(
            RateLimitMiddleware,
            limit=settings.RATE_LIMIT_REQUESTS,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,  # required for the refresh cookie
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
        max_age=600,
    )
    if settings.ALLOWED_HOSTS != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    # Probes are also mounted unversioned: orchestrators and load balancers
    # should not have to track the API version to know if a pod is healthy.
    app.include_router(health.router, include_in_schema=False)

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "name": settings.PROJECT_NAME,
                "version": settings.VERSION,
                "docs": "/docs" if not settings.is_production else None,
                "api": settings.API_V1_PREFIX,
            }
        )

    return app


app = create_app()

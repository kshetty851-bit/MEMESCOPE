"""Liveness and readiness probes.

`/live` answers "is the process up" and must never touch a dependency.
`/ready` answers "can this instance serve traffic" and checks Postgres + Redis;
Kubernetes and the compose healthchecks use it to gate rollout.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.redis import redis_healthcheck
from app.db.session import database_healthcheck
from app.schemas.common import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/live", response_model=HealthStatus, summary="Liveness probe")
async def liveness() -> HealthStatus:
    return HealthStatus(
        status="ok", version=settings.VERSION, environment=settings.ENVIRONMENT
    )


@router.get("/ready", response_model=HealthStatus, summary="Readiness probe")
async def readiness(response: Response) -> HealthStatus:
    checks = {
        "database": await database_healthcheck(),
        "redis": await redis_healthcheck(),
    }
    degraded = any(check["status"] != "ok" for check in checks.values())
    if degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthStatus(
        status="degraded" if degraded else "ok",
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        checks=checks,
    )

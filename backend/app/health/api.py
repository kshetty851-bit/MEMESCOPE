"""`GET /api/v1/health/pipeline`.

Kept separate from `endpoints/health.py`, which owns the two probes an
orchestrator polls at high frequency and which must stay dependency-free
(`/live`) or near-free (`/ready`). This one runs half a dozen aggregate
queries; putting it behind the same path as a liveness probe would invite
someone to point a 1-second kubelet check at it.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import DbSession
from app.health.schemas import PipelineHealth
from app.health.service import PipelineHealthService

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/pipeline",
    response_model=PipelineHealth,
    summary="Per-stage pipeline health",
)
async def pipeline_health(session: DbSession, response: Response) -> PipelineHealth:
    """Report what each pipeline stage has actually produced.

    Returns 503 when `overall` is `down`, so this endpoint can drive an
    external monitor without that monitor having to parse the body. A
    `degraded` roll-up still returns 200: it is a warning, and paging on it
    would train the reader to ignore the page.
    """
    health = await PipelineHealthService(session).snapshot()
    if health.overall == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health

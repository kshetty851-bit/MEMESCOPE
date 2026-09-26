"""`GET /api/v1/health/pipeline`.

Kept separate from `endpoints/health.py`, which owns the two probes an
orchestrator polls at high frequency and which must stay dependency-free
(`/live`) or near-free (`/ready`). This one runs half a dozen aggregate
queries; putting it behind the same path as a liveness probe would invite
someone to point a 1-second kubelet check at it.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Response, status

from app.api.deps import DbSession
from app.core.config import settings
from app.health.research_data import ResearchDataHealthService
from app.health.schemas import (
    PipelineHealth,
    ResearchDataHealth,
    WalletPauseOut,
)
from app.health.service import PipelineHealthService

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/research-data",
    response_model=ResearchDataHealth,
    summary="Whether the data the next research round depends on is being collected",
)
async def research_data_health(session: DbSession) -> ResearchDataHealth:
    payload = await ResearchDataHealthService(session).snapshot()
    return ResearchDataHealth(
        **payload,
        wallets=WalletPauseOut(
            paper_entries_paused=settings.PAPER_WALLET_ENTRIES_PAUSED,
            karthik_entries_paused=settings.KARTHIK_ENTRIES_PAUSED,
            reason=settings.WALLET_ENTRIES_PAUSE_REASON,
        ),
    )


#: One snapshot per minute, shared. It costs ~20s of queries on prod's tables,
#: and every open HQ tab polls it: without this, two viewers ran it twice at
#: once, and a slow run piled up behind itself (2026-09-26: six workers busy
#: on one abandoned count). The lock makes concurrent callers wait for the one
#: run in flight rather than start their own.
# ponytail: per-process cache; a Redis copy if more backend replicas are added.
_PIPELINE_TTL_S = 60.0
_pipeline_cache: tuple[float, PipelineHealth] | None = None
_pipeline_lock = asyncio.Lock()


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
    global _pipeline_cache
    async with _pipeline_lock:
        if _pipeline_cache is None or time.monotonic() - _pipeline_cache[0] > _PIPELINE_TTL_S:
            _pipeline_cache = (time.monotonic(), await PipelineHealthService(session).snapshot())
        health = _pipeline_cache[1]
    if health.overall == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health

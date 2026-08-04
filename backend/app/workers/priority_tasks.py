"""Celery entry point for the priority enrichment lane.

Membership is recomputed rather than accumulated, so this beat must run often
enough that a token entering the Radar's visible ranks reaches the lane before a
user notices it is stale. Every minute: the lane's own cadence is fifteen
seconds, so a minute of membership lag costs at most four refreshes on one token.

No lock, matching every other beat here. The pass is idempotent — it derives the
set from current state and issues two predicated UPDATEs, so a duplicate run
writes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.services.market.priority import refresh_priority_lane
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.workers.priority_tasks.refresh_priority_lane")
def refresh_priority_lane_task() -> dict[str, Any]:
    """Recompute which tokens the product is displaying."""
    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    if not settings.FEATURE_PRIORITY_ENRICHMENT_ENABLED:
        # Reported rather than silently skipped: a lane that stopped being
        # maintained shows up as staleness on the homepage long before anyone
        # thinks to check whether the beat is running.
        logger.info("priority_lane_skipped", reason="disabled")
        return {"skipped": "disabled"}

    async with SessionFactory() as session:
        membership = await refresh_priority_lane(session, now=datetime.now(UTC))
        await session.commit()

    logger.info("priority_lane_refreshed", **membership.as_dict())
    return dict(membership.as_dict())

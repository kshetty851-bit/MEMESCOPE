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
from app.services.market.priority import refresh_nursery_lane, refresh_priority_lane
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.workers.priority_tasks.refresh_priority_lane")
def refresh_priority_lane_task() -> dict[str, Any]:
    """Recompute which tokens the product is displaying."""
    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    result: dict[str, Any] = {}

    if settings.FEATURE_PRIORITY_ENRICHMENT_ENABLED:
        async with SessionFactory() as session:
            membership = await refresh_priority_lane(session, now=datetime.now(UTC))
            await session.commit()
        logger.info("priority_lane_refreshed", **membership.as_dict())
        result = dict(membership.as_dict())
    else:
        # Reported rather than silently skipped: a lane that stopped being
        # maintained shows up as staleness on the homepage long before anyone
        # thinks to check whether the beat is running.
        logger.info("priority_lane_skipped", reason="disabled")
        result = {"skipped": "disabled"}

    # **Unconditional, and deliberately not behind the display lane's flag.**
    # `register_token` admits every discovery to the nursery whenever the
    # capacity setting allows it, and this pass is the only code that ever
    # takes a token *out* — by age, or by the capacity trim. Gating the two on
    # different switches meant flipping `FEATURE_PRIORITY_ENRICHMENT_ENABLED`
    # off (its purpose as an incident lever) left admission running with
    # enforcement stopped: the lane would grow without bound and never expire,
    # which is precisely the backlog it exists to escape.
    #
    # It also runs at capacity zero, because that is how the lane is drained:
    # the trim's OFFSET 0 demotes every member. Skipping the call would strand
    # whoever was already inside, outranking the whole normal population
    # indefinitely.
    #
    # Its own transaction, after the display lane, so a nursery failure can
    # never cost the display lane its refresh.
    async with SessionFactory() as session:
        nursery = await refresh_nursery_lane(session, now=datetime.now(UTC))
        await session.commit()
    # Logged even when nothing moved, for the same reason as the requeue beat:
    # a quiet maintenance pass and a dead one look identical otherwise.
    logger.info("nursery_lane_refreshed", **nursery.as_dict())
    result["nursery"] = dict(nursery.as_dict())

    return result

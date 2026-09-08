"""The social collector's beat. Contained, locked, dark by default.

Every ten minutes, not every minute. Three reasons, in order: it is somebody
else's API and two calls a poll is already the polite ceiling; comment activity
does not move on a one-minute scale; and the derived quantity is a RATE, so a
wider gap makes the denominator larger and the rate less noisy.

Its own advisory lock. Two overlapping polls would write two batches with
different timestamps for the same coins, and the velocity read would then
divide a real change by a near-zero gap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.pumpfun.social import fetch, to_rows
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

SOCIAL_LOCK_KEY = 0x534F4349


@celery_app.task(name="app.pumpfun.social_scheduler.pumpfun_social_tick")
def pumpfun_social_tick() -> dict[str, Any]:
    """Record one point-in-time reading of pump.fun's comment activity."""
    return run_async(_tick())


async def _tick() -> dict[str, Any]:
    if not getattr(settings, "FEATURE_PUMPFUN_SOCIAL_ENABLED", False):
        return {"skipped": "social_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, SOCIAL_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "social_already_running"}
            readings = await fetch()
            if not readings:
                # Not a failure worth raising: the provider is third-party and
                # a missed poll costs one gap in a rate, not a broken series.
                return {"readings": 0, "skipped": "nothing_returned"}
            rows = to_rows(readings, now=datetime.now(UTC))
            session.add_all(rows)
            await session.commit()
    except Exception:
        logger.exception("pumpfun_social_tick_failed")
        return {"failed": True}
    by_sort: dict[str, int] = {}
    for r in readings:
        by_sort[r.source_sort] = by_sort.get(r.source_sort, 0) + 1
    logger.info("pumpfun_social_tick", readings=len(rows), **by_sort)
    return {"readings": len(rows), **by_sort}

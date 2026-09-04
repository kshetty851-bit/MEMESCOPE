"""The PumpFun Lab's beat. Contained, locked, and dark by default.

Every minute, like the tournaments it sits beside. The cadence is already a
compromise: the leader holds a median of 8.5 minutes, so a one-minute poll can
put us up to a minute behind a trade that lasts eight. That lag is recorded per
signal rather than assumed away, and it is one of the things the experiment is
measuring.

Its own advisory lock. Two overlapping ticks could each see the same unrecorded
leader trade and both open a position; the unique constraint on `signature`
would catch the second write, but only after the first had already spent the
cash. The lock stops the race before it costs anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.pumpfun.service import PumpfunService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

PUMPFUN_LOCK_KEY = 0x50554D50


@celery_app.task(name="app.pumpfun.scheduler.pumpfun_tick")
def pumpfun_tick() -> dict[str, Any]:
    """Poll the leader, mirror what is new, then settle and mark the book."""
    return run_async(_pumpfun_tick())


async def _pumpfun_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_PUMPFUN_LAB_ENABLED", False):
        return {"skipped": "pumpfun_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, PUMPFUN_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "pumpfun_already_running"}
            outcome = await PumpfunService(session).tick(now=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception("pumpfun_tick_failed")
        return {"failed": True}
    return outcome

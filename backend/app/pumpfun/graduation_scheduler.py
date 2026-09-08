"""The graduation collector's beat. Contained, locked, dark by default.

Every minute, because the whole value of this collector is that the first
sighting is close to the real graduation. At a five-minute interval the stamp
would carry five minutes of error into a measurement whose first target is at
five minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.pumpfun import graduation
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

GRADUATION_LOCK_KEY = 0x47524144


@celery_app.task(name="app.pumpfun.graduation_scheduler.pumpfun_graduation_tick")
def pumpfun_graduation_tick() -> dict[str, Any]:
    """Stamp new graduations, then take whichever follow-up marks are due."""
    return run_async(_tick())


async def _tick() -> dict[str, Any]:
    if not getattr(settings, "FEATURE_PUMPFUN_GRADUATION_ENABLED", False):
        return {"skipped": "graduation_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, GRADUATION_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "graduation_already_running"}
            now = datetime.now(UTC)
            found = await graduation.discover(session, now=now)
            marked = await graduation.mark(session, now=now)
            await session.commit()
    except Exception:
        logger.exception("pumpfun_graduation_tick_failed")
        return {"failed": True}
    if found.get("stamped") or marked.get("written"):
        logger.info("pumpfun_graduation_tick", **found, **marked)
    return {"discover": found, "mark": marked}

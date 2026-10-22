"""Every 10 minutes: read every recent graduation, then run the two paper books."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)
TASK = "app.labs.longwatch.scheduler.longwatch_tick"
LOCK = 0x4C4F4E47


@celery_app.task(name=TASK, soft_time_limit=420, time_limit=480)
def longwatch_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(_tick())


async def _tick() -> dict[str, Any]:
    import httpx
    from sqlalchemy import func, select

    from app.db.session import SessionFactory
    from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
    from app.labs.longwatch import service

    now = datetime.now(UTC).replace(microsecond=0)
    try:
        async with SessionFactory() as session:
            if not await session.scalar(select(func.pg_try_advisory_xact_lock(DRY_RUN_LOCK_NAMESPACE, LOCK))):
                return {"skipped": "already_running"}
            async with httpx.AsyncClient(headers={"Accept": "application/json"}) as client:
                read = await service.collect(session, now, client)
            closed = await service.manage(session, now)
            opened = await service.decide(session, now)
            await session.commit()
            return {"readings": read, "closed": closed, "decisions": dict(opened)}
    except Exception:  # never raise into the beat
        logger.exception("longwatch_tick_failed")
        return {"failed": True}

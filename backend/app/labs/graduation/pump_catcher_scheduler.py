"""Every 5 minutes: price the Pump Catcher's exit for the book's new positions."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)
TASK = "app.labs.graduation.pump_catcher_scheduler.pump_catcher_refresh"


@celery_app.task(name=TASK, soft_time_limit=280)
def pump_catcher_refresh() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.db.session import SessionFactory
    from app.labs.graduation import pump_catcher

    try:
        async with SessionFactory() as session:
            return await pump_catcher.refresh(session, await init_redis())
    except Exception:  # never raise into the beat
        logger.exception("pump_catcher_refresh_failed")
        return {"failed": True}


celery_app.conf.beat_schedule.setdefault(
    "pump-catcher-refresh",
    {"task": TASK, "schedule": 300.0, "options": {"expires": 290}},
)

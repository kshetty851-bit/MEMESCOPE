"""Every 30 minutes: refresh the track record (`service.refresh`)."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)
TASK = "app.track_record.scheduler.track_record_refresh"


@celery_app.task(name=TASK)
def track_record_refresh() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.db.session import SessionFactory
    from app.track_record import service

    try:
        async with SessionFactory() as session:
            return await service.refresh(session, await init_redis())
    except Exception:  # never raise into the beat
        logger.exception("track_record_refresh_failed")
        return {"failed": True}


celery_app.conf.beat_schedule.setdefault(
    "track-record-refresh",
    {"task": TASK, "schedule": 1800.0, "options": {"expires": 1700}},
)

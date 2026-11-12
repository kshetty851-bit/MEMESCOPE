"""Every 10 minutes: Mood Lab data, new trades, due exits."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)
TASK = "app.labs.mood.scheduler.mood_refresh"


@celery_app.task(name=TASK, soft_time_limit=280)
def mood_refresh() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.labs.mood import mood

    try:
        return await mood.refresh(await init_redis())
    except Exception:  # never raise into the beat
        logger.exception("mood_refresh_failed")
        return {"failed": True}


celery_app.conf.beat_schedule.setdefault(
    "mood-refresh",
    {"task": TASK, "schedule": 600.0, "options": {"expires": 590}},
)

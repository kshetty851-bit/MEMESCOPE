"""Every two minutes: rebuild the newspaper bundle (`refresh.build`)."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)
TASK = "app.newsroom.scheduler.newsroom_refresh"
INTERVAL_SECONDS = 120


@celery_app.task(name=TASK, soft_time_limit=100, time_limit=115)
def newsroom_refresh() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.db.session import SessionFactory
    from app.newsroom import refresh

    try:
        return await refresh.build(SessionFactory, await init_redis())
    except Exception:  # never raise into the beat
        logger.exception("newsroom_refresh_failed")
        return {"error": "newsroom_refresh_failed"}


celery_app.conf.beat_schedule.setdefault(
    "newsroom-refresh",
    {
        "task": TASK,
        "schedule": float(INTERVAL_SECONDS),
        # A late run is dropped: the next one is already fresher.
        "options": {"expires": INTERVAL_SECONDS - 10},
    },
)

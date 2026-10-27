"""Every 5 minutes: decide the Fresh Catch Lab's new graduations."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)
TASK = "app.labs.graduation.fresh_catch_scheduler.fresh_catch_refresh"


@celery_app.task(name=TASK, soft_time_limit=280)
def fresh_catch_refresh() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.db.session import SessionFactory
    from app.labs.graduation import fresh_catch

    try:
        async with SessionFactory() as session:
            return await fresh_catch.refresh(session, await init_redis())
    except Exception:  # never raise into the beat
        logger.exception("fresh_catch_refresh_failed")
        return {"failed": True}


HELIUS_TASK = "app.labs.graduation.fresh_catch_scheduler.fresh_catch_helius"


@celery_app.task(name=HELIUS_TASK, soft_time_limit=55)
def fresh_catch_helius() -> dict[str, Any]:
    """The one-week Helius recording of new pools' first-seconds buys and sells."""
    from app.workers.runtime import run_async

    async def go() -> dict[str, Any]:
        from app.core.redis import init_redis
        from app.db.session import SessionFactory
        from app.labs.graduation import fresh_catch_helius as fh

        try:
            async with SessionFactory() as session:
                return await fh.refresh(session, await init_redis())
        except Exception:  # never raise into the beat
            logger.exception("fresh_catch_helius_failed")
            return {"failed": True}

    return run_async(go())


celery_app.conf.beat_schedule.setdefault(
    "fresh-catch-helius",
    {"task": HELIUS_TASK, "schedule": 60.0, "options": {"expires": 55}},
)
celery_app.conf.beat_schedule.setdefault(
    "fresh-catch-refresh",
    {"task": TASK, "schedule": 300.0, "options": {"expires": 290}},
)

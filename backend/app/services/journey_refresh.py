"""Every minute: build the homepage journey figures into Redis (see
`app.api.v1.endpoints.journey`), so a visitor reads them instead of waiting."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)
TASK = "app.services.journey_refresh.journey_refresh"


@celery_app.task(name=TASK, soft_time_limit=50)
def journey_refresh() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    from app.api.v1.endpoints import journey
    from app.db.session import SessionFactory

    try:
        async with SessionFactory() as session:
            await journey.store(session)
        return {"stored": True}
    except Exception:  # never raise into the beat
        logger.exception("journey_refresh_failed")
        return {"failed": True}


celery_app.conf.beat_schedule.setdefault(
    "journey-refresh",
    {"task": TASK, "schedule": 60.0, "options": {"expires": 55}},
)

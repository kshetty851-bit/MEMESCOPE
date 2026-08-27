"""Arena beat. Research simulation — it can never open a real or paper position.

Wrapped so an Arena failure is contained: the task logs and returns rather than
raising into the beat, exactly as the research collectors do. The Arena is
instrumentation, and instrumentation must never be able to disturb the systems
it observes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.arena.service import ArenaService
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.arena.scheduler.arena_tick")
def arena_tick() -> dict[str, Any]:
    """Judge due checkpoints, then advance open virtual positions."""
    return run_async(_arena_tick())


async def _arena_tick() -> dict[str, Any]:
    if not settings.FEATURE_ARENA_ENABLED:
        return {"skipped": "arena_disabled"}
    now = datetime.now(UTC)
    try:
        async with SessionFactory() as session:
            service = ArenaService(session)
            await service.activate(valid_from=settings.arena_valid_from or now)
            decided = await service.evaluate_due(now=now)
            settled = await service.settle(now=now)
            await session.commit()
        return {"decided": decided, "settled": settled}
    except Exception:
        logger.exception("arena_tick_failed")
        return {"failed": True}

"""Celery entry point for event cycles.

Bounded per run, like the Radar sweep, and for the same reason: the candidate
set grows as the platform collects, and a task that takes longer every day
eventually overruns its own interval.

The cycle deliberately follows the Radar's own rotation rather than inventing a
second schedule. Events are only interesting for projects the Radar has an
opinion about, and running the two on different cadences would mean comparing a
fresh reading against a cache written by a different population.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.events.orchestrator import EventOrchestrator
from app.radar.repository import RadarRepository
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.events.scheduler.event_cycle")
def event_cycle(limit: int | None = None) -> dict[str, Any]:
    """Run one event cycle over the tokens the Radar currently tracks."""
    return run_async(_event_cycle(limit))


async def _event_cycle(limit: int | None = None) -> dict[str, Any]:
    if not settings.FEATURE_RADAR_ENABLED:
        # Events derive from analyst readings, which derive from the Radar's
        # series. With the Radar off there is nothing to compare.
        logger.info("event_cycle_skipped", reason="radar_disabled")
        return {"skipped": "radar_disabled"}

    batch = limit or settings.RADAR_SWEEP_BATCH_LIMIT

    async with SessionFactory() as session:
        # Tracked entries first: these are the projects a user may actually be
        # watching, so a change to one of them is the most valuable event the
        # platform can emit.
        mints = await RadarRepository(session).tracked_mints(limit=batch)
        summary = await EventOrchestrator(session).run_cycle(mints)

    return summary.as_dict()

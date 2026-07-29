"""Radar background jobs.

The launch scanner keeps discovering; this keeps *re-evaluating*. That split is
the whole point of the Radar: a project becomes an opportunity long after it was
discovered, and nothing in the existing pipeline would ever look at it again.

Tasks call `run_async()` rather than `asyncio.run()` — the convention recorded in
§12. The module-global engine's pooled connections otherwise leak across event
loops and the *second* task in a worker fails with `got Future attached to a
different loop`.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.radar.service import RadarService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.radar.scheduler.radar_sweep")
def radar_sweep(limit: int | None = None) -> dict[str, Any]:
    """Re-evaluate a batch of tokens and update the Radar.

    Bounded per run rather than sweeping everything: the candidate set grows
    without limit as the platform collects, and a task that takes longer each
    week eventually overruns its own schedule. Ordering by most recently
    observed means the budget is spent on tokens that are actually live.
    """
    return run_async(_radar_sweep(limit))


async def _radar_sweep(limit: int | None = None) -> dict[str, Any]:
    if not settings.FEATURE_RADAR_ENABLED:
        return {"skipped": "radar_disabled"}

    batch = limit or settings.RADAR_SWEEP_BATCH_LIMIT
    async with SessionFactory() as session:
        return await RadarService(session).sweep(limit=batch)

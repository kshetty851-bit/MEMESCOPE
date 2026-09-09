"""Beat entry for `lab_coverage`. Deliberately thin.

The labs judge a coin ten minutes after it is first seen. This runs every
minute over coins seen in the last twenty, so a verdict is on disk before the
checkpoint that needs it rather than after.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.security.lab_coverage import cover_lab_candidates
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.security.lab_scheduler.cover_lab_candidates_tick")
def cover_lab_candidates_tick() -> dict[str, Any]:
    return run_async(_tick())


async def _tick() -> dict[str, Any]:
    if not settings.TOKEN_SECURITY_EVALUATION_ENABLED:
        return {"skipped": "security_evaluation_disabled"}
    try:
        async with SessionFactory() as session:
            offered = await cover_lab_candidates(session, now=datetime.now(UTC))
            await session.commit()
    except Exception:
        # Observation must never be able to stop the labs it observes.
        logger.exception("security_lab_coverage_failed")
        return {"failed": True}
    return {"offered": offered}

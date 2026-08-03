"""Celery entry point for the opportunity lifecycle.

Detection rides enrichment writes, so an opportunity **opens** the moment its
token is enriched. Nothing else runs on that path: closing needs no new data,
only the passage of time, and a token whose signal has gone quiet stops being
enriched into detection at exactly the moment it most needs reviewing. Without
this task the board only ever grows — a two-day-old graduation stays ACTIVE, the
permanent record never receives it, and archival never frees the token to open a
new generation.

No lock, matching `score_sweep` and `event_cycle`. Beat is a single service, so
the only overlap is a run that outlives its own interval, and that costs nothing
here: every transition is a pure function of stored timestamps against `now`
(`resolve_status`, `should_archive`), so a second pass over the same rows
resolves the same states and writes no new events. The batch is bounded and
ordered oldest-confirmed-first with a mint tiebreak in `due_for_review`, which is
what keeps a growing board from starving its own tail — the failure that
livelocked the score sweep.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.opportunities.engine import OpportunityEngine
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.opportunities.scheduler.opportunity_review")
def opportunity_review() -> dict[str, Any]:
    """Advance expiry, closure and archival for one bounded page of the board."""
    return run_async(_opportunity_review())


async def _opportunity_review() -> dict[str, Any]:
    if not settings.FEATURE_OPPORTUNITY_ENGINE_ENABLED:
        # With detection off nothing opens, so nothing can be owed a closure.
        # Reported rather than silently skipped: an engine that stopped
        # advancing must be visible in the task log, not inferred from a board
        # that quietly stopped changing.
        logger.info("opportunity_review_skipped", reason="engine_disabled")
        return {"skipped": "engine_disabled"}

    async with SessionFactory() as session:
        outcome = await OpportunityEngine(session).review_expired()
        # The worker owns its session and commits explicitly; the engine only
        # flushes. Committing here rather than inside `review_expired` is what
        # lets the enrichment worker call the same code inside its own
        # transaction.
        await session.commit()

    return outcome.as_dict()

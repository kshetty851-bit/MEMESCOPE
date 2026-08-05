"""Celery entry point for enrichment recovery.

**Dead-lettering used to be terminal.** `requeue_dead_letters` existed on the
repository, documented as an operator action, and nothing in the codebase ever
called it — so a token removed from the queue by one bad minute was gone until
somebody noticed and intervened by hand. On 2026-08-05 a 60-second DexScreener
outage parked 163 of the 200 tokens in the priority enrichment lane, including
ten of the paper wallet's twelve holdings, and they stayed parked long after the
provider recovered.

The root cause is fixed elsewhere — `MarketEnrichmentService._defer` no longer
charges a provider outage to the tokens it never asked about. This beat is the
second half: it makes the dead-letter state a **quarantine rather than a
grave**, so any future mistake, from any cause, heals itself.

Bounded and idle-gated on purpose. Only tokens that have sat dead-lettered for
`ENRICHMENT_DEAD_LETTER_RETRY_MINUTES` are readmitted, at most
`ENRICHMENT_DEAD_LETTER_REQUEUE_LIMIT` per pass — a genuinely broken mint should
cost one wasted call per interval, not one per pass, and a large backlog should
drain gradually rather than arrive as a spike on a provider that may still be
unwell.

No lock, matching every other beat here: the pass is a single predicated UPDATE,
so a duplicate run readmits nothing twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.repositories.market import EnrichmentStateRepository
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.workers.enrichment_tasks.requeue_dead_letters")
def requeue_dead_letters() -> dict[str, Any]:
    """Readmit dead-lettered tokens that have served their quarantine."""
    return run_async(_requeue())


async def _requeue() -> dict[str, Any]:
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        requeued = await EnrichmentStateRepository(session).requeue_dead_letters(
            now=now,
            limit=settings.ENRICHMENT_DEAD_LETTER_REQUEUE_LIMIT,
            idle_for=timedelta(minutes=settings.ENRICHMENT_DEAD_LETTER_RETRY_MINUTES),
        )
        # The worker owns its session and commits explicitly.
        await session.commit()

    # Logged even at zero. A recovery beat that only speaks when it acts is
    # indistinguishable from one that stopped running, and the failure this
    # exists to catch is exactly "nothing has refreshed for an hour".
    logger.info("enrichment_dead_letters_requeued", requeued=requeued)
    return {"requeued": requeued}

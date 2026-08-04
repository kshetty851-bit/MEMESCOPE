"""Celery entry point for the paper wallet.

Nothing else advances the simulation. Entries depend on the Radar's ranking and
exits depend on the passage of price, and neither rides a write path the way
opportunity detection rides enrichment — a position whose token stopped being
enriched is exactly the one most likely to be sitting through its stop.

No lock, matching `score_sweep`, `event_cycle` and `opportunity_review`. Beat is
a single service, so the only overlap is a run that outlives its own interval,
and that costs nothing here: exits are resolved from the observation series
against a stored watermark, and entries insert with `ON CONFLICT DO NOTHING`
against a unique index. A second pass over the same rows resolves the same
exits, opens no second position, and writes nothing new.

The batch is bounded and ordered oldest-watermark-first, which keeps a growing
book from starving its own tail — the failure that livelocked the score sweep.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.paper.service import PaperWalletService, utcnow
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.paper.scheduler.paper_review")
def paper_review() -> dict[str, Any]:
    """Settle exits, then open what the strategy can fund."""
    return run_async(_paper_review())


async def _paper_review() -> dict[str, Any]:
    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        # Reported rather than silently skipped: a simulation that stopped
        # advancing must be visible in the task log, not inferred from a wallet
        # whose numbers quietly stopped changing.
        logger.info("paper_review_skipped", reason="wallet_disabled")
        return {"skipped": "wallet_disabled"}

    async with SessionFactory() as session:
        outcome = await PaperWalletService(session).review(now=utcnow())
        # The worker owns its session and commits explicitly; the service only
        # flushes, so the same code can run inside another transaction.
        await session.commit()

    logger.info("paper_review", **outcome.as_dict())
    return outcome.as_dict()

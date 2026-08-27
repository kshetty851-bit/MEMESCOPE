"""Celery entry point for the Karthik wallet.

One beat, every minute, doing one pass. Karthik has no Radar-triggered
acceleration path and does not want one: its entry decision is priced from the
freshest observation at the moment it looks, so running more often changes
*when* a decision is recorded and therefore *what price it gets*. A single
predictable cadence is what makes "Karthik entered 40 seconds after admission"
a measurement rather than an artefact of how many things happened to fire.

**Its own advisory lock, its own task, its own session.** Nothing here can
delay, roll back or interfere with `app.paper.scheduler.paper_review`: a
Karthik failure raises inside this task and leaves the paper wallet's committed
work untouched, because the two never share a transaction.

There is no feature flag. Karthik runs when a wallet row exists and does
nothing when it does not — see `app/core/config.py` for why a flag would have
been a weaker copy of that fact, and a dangerous one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_live_update
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.karthik.service import KarthikService, utcnow
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

# Deterministic two-int advisory-lock key, distinct from the paper review's
# ("MEME"/"PAPR") so the two wallets never block each other. These are
# ASCII-derived constants, not Python's process-randomised hash().
KARTHIK_REVIEW_LOCK_NAMESPACE = 0x4D454D45  # "MEME"
KARTHIK_REVIEW_LOCK_KEY = 0x4B525448  # "KRTH"


@celery_app.task(name="app.karthik.scheduler.karthik_review")
def karthik_review() -> dict[str, Any]:
    """Settle exits, then decide new Track Record admissions."""
    return run_async(_karthik_review())


async def _karthik_review() -> dict[str, Any]:
    async with SessionFactory() as session:
        if not await acquire_karthik_review_lock(session):
            await session.rollback()
            logger.info("karthik_review_skipped", reason="review_already_running")
            return {"skipped": "review_already_running"}

        outcome = await KarthikService(session).review(now=utcnow())
        if outcome is None:
            await session.rollback()
            # Reported rather than silently skipped: a wallet that never
            # activated must be visible in the task log, not inferred from a
            # page that quietly shows nothing.
            logger.info("karthik_review_skipped", reason="not_activated")
            return {"skipped": "not_activated"}

        # The worker owns its session and commits explicitly; the service only
        # flushes, so the same code can run inside another transaction.
        await session.commit()

    await publish_live_update("karthik.changed")
    logger.info("karthik_review", **outcome.as_dict())
    return outcome.as_dict()


async def acquire_karthik_review_lock(session: AsyncSession) -> bool:
    """Serialize the whole Karthik pass, non-blocking.

    Karthik reviews are coalescible: every pass reads current state and the next
    beat is a minute away. So a duplicate exits immediately rather than sitting
    in a backlog and replaying stale intent later. PostgreSQL releases the lock
    at commit or rollback.

    This is a convenience, not the correctness guarantee. Exactly-once entry is
    held by `uq_karthik_opportunities_wallet_mint` and
    `uq_karthik_positions_wallet_mint` — two passes that somehow ran together
    would still produce one position each way.
    """
    acquired = await session.scalar(
        select(
            func.pg_try_advisory_xact_lock(
                KARTHIK_REVIEW_LOCK_NAMESPACE, KARTHIK_REVIEW_LOCK_KEY
            )
        )
    )
    return bool(acquired)

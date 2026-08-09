"""Celery entry point for the paper wallet.

Two things advance the simulation, and they answer different questions.

* **The five-minute beat** covers the passage of price. A position whose token
  stopped being enriched is exactly the one most likely to be sitting through
  its trailing stop, and no write path would ever visit it.
* **Every Radar refresh** enqueues a pass of its own (`radar_sweep` and
  `pumpfun_radar_scan` both call `request_review`). Sprint 30 §8 requires the
  ranking and the wallet to move together: a token that reaches the top of the
  Radar at :15 should not wait for :20 to be considered, and cash freed by an
  exit should be redeployed against the ranking that exists now rather than the
  one from five minutes ago.

The second is a trigger, not a second evaluator. It runs the same `review`, and
running it more often changes only when a decision is *recorded*: exits resolve
against the stored observation series, so the trade that comes out is the same
one whatever the schedule did.

The complete paper review is serialized with a transaction-scoped PostgreSQL
advisory lock. A scheduled beat pass and a Radar-triggered pass may still be
enqueued at the same time, but the second pass coalesces and exits quickly while
the first transaction owns the review. This preserves the five-minute safety
review without building a backlog of stale duplicate wallet evaluations.

The batch is bounded and ordered oldest-watermark-first, which keeps a growing
book from starving its own tail — the failure that livelocked the score sweep.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import publish_live_update
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.paper.service import PaperWalletService, utcnow
from app.paper.shadow import ShadowPaperService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

# Deterministic two-int advisory-lock key for the complete paper-review
# transaction. These are ASCII-derived constants ("MEME", "PAPR") expressed as
# signed 32-bit integers, not Python's process-randomised hash().
PAPER_REVIEW_LOCK_NAMESPACE = 0x4D454D45
PAPER_REVIEW_LOCK_KEY = 0x50415052


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
        if not await acquire_paper_review_lock(session):
            await session.rollback()
            logger.info("paper_review_skipped", reason="review_already_running")
            return {"skipped": "review_already_running"}

        now = utcnow()
        outcome = await PaperWalletService(session).review(now=now)
        shadow_outcome = await ShadowPaperService(session).review(now=now)
        # The worker owns its session and commits explicitly; the service only
        # flushes, so the same code can run inside another transaction.
        await session.commit()

    # The read model includes current marks and the idle explanation, so a
    # completed review is relevant even when it opened or closed no position.
    await publish_live_update("paper.changed")

    logger.info("paper_review", **outcome.as_dict(), shadow=shadow_outcome.as_dict())
    return {**outcome.as_dict(), "shadow": shadow_outcome.as_dict()}


async def acquire_paper_review_lock(session: AsyncSession) -> bool:
    """Try to serialize the whole paper review transaction.

    Paper reviews are coalescible: every pass reads the current database state,
    and both the scheduled beat and Radar-triggered pass will run again. So this
    uses the non-blocking transaction-scoped variant. If another review already
    holds the lock, the stale duplicate exits quickly instead of sitting in a
    Celery backlog and replaying old intent later. PostgreSQL releases the lock
    automatically at commit/rollback.
    """

    acquired = await session.scalar(
        select(
            func.pg_try_advisory_xact_lock(PAPER_REVIEW_LOCK_NAMESPACE, PAPER_REVIEW_LOCK_KEY)
        )
    )
    return bool(acquired)


def request_review(*, trigger: str) -> None:
    """Ask for a wallet pass after something changed the Radar.

    Enqueued rather than run inline: the Radar sweep owns its own transaction
    and its own timing budget, and a wallet pass that failed inside it would
    roll back a completed sweep. As a separate task the worst case is a pass
    that does not happen, which the five-minute beat then picks up.

    Swallows its own failure for the same reason. The wallet is downstream of
    the Radar; a broker hiccup must not turn a successful sweep into a failed
    task and a retry that re-evaluates the whole Radar.
    """
    if not settings.FEATURE_PAPER_WALLET_ENABLED:
        return
    try:
        paper_review.delay()
    except Exception:  # pragma: no cover - broker failure path
        logger.warning("paper_review_enqueue_failed", trigger=trigger, exc_info=True)
    else:
        logger.info("paper_review_requested", trigger=trigger)

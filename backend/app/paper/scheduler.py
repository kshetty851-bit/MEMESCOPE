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

No lock, matching `score_sweep`, `event_cycle` and `opportunity_review`. The
overlap that can now happen — a beat pass and a Radar-triggered pass at once —
costs nothing: exits are resolved against a stored watermark, and entries insert
with `ON CONFLICT DO NOTHING` against a unique index. A second pass over the same
rows resolves the same exits, opens no second position, and writes nothing new.

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

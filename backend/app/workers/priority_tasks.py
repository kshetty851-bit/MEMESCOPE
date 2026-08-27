"""Celery entry point for the priority enrichment lane.

Membership is recomputed rather than accumulated, so this beat must run often
enough that a token entering the Radar's visible ranks reaches the lane before a
user notices it is stale. Every minute: the lane's own cadence is fifteen
seconds, so a minute of membership lag costs at most four refreshes on one token.

No lock, matching every other beat here. The pass is idempotent — it derives the
set from current state and issues two predicated UPDATEs, so a duplicate run
writes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.paper.repository import PaperRepository
from app.services.market.priority import (
    refresh_nursery_lane,
    refresh_priority_lane,
    reprime_open_positions,
)
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.workers.priority_tasks.refresh_priority_lane")
def refresh_priority_lane_task() -> dict[str, Any]:
    """Recompute which tokens the product is displaying."""
    return run_async(_refresh())


async def _refresh() -> dict[str, Any]:
    result: dict[str, Any] = {}

    # ── RECOVERY ORDER ──────────────────────────────────────────────────
    #
    # Committed capital is re-primed FIRST, before lane membership is
    # recomputed and long before the nursery admits a single speculative
    # launch. The order is the whole point, and it is the order the beat
    # executes in rather than a comment describing an intention:
    #
    #   1. re-prime stale open positions        (here, own transaction)
    #   2. recompute display-lane membership    (refresh_priority_lane)
    #   3. admit and trim the nursery           (refresh_nursery_lane)
    #   4. allow new entries                    (paper.review, only once the
    #                                            census says the book is fresh)
    #
    # Step 4 is not enforced here and must not be: it is enforced by evidence
    # in `market_health.assess`, which keeps entries blocked while any
    # recoverable open position is stale. A recovery defined by "this beat ran"
    # would be a sleep timer wearing a different name — it would report
    # complete whether or not a single quote had arrived.
    #
    # Its own transaction, and first, so that a failure anywhere below cannot
    # cost the open book its refresh. This is the one step that is about money
    # already committed rather than about what the product displays.
    reprimed = 0
    try:
        async with SessionFactory() as session:
            stale = await PaperRepository(session).stale_open_mints(
                now=datetime.now(UTC)
            )
            if stale:
                reprimed = await reprime_open_positions(
                    session, stale, now=datetime.now(UTC)
                )
                await session.commit()
                # WARNING, not info: an open position with no recent price is
                # the condition that cost the wallet $500 on 2026-08-21, and
                # it produced no log line at any level while it happened.
                logger.warning(
                    "open_positions_reprimed",
                    stale=len(stale),
                    rows_moved=reprimed,
                    mints=stale[:20],
                )
    except Exception:
        # Never let the re-prime take the lane refresh down with it. A lane
        # that stopped being maintained is a slower version of the same
        # outage.
        logger.warning("open_position_reprime_failed", exc_info=True)
    result["open_positions_reprimed"] = reprimed

    if settings.FEATURE_PRIORITY_ENRICHMENT_ENABLED:
        async with SessionFactory() as session:
            membership = await refresh_priority_lane(session, now=datetime.now(UTC))
            await session.commit()
        logger.info("priority_lane_refreshed", **membership.as_dict())
        result.update(membership.as_dict())
    else:
        # Reported rather than silently skipped: a lane that stopped being
        # maintained shows up as staleness on the homepage long before anyone
        # thinks to check whether the beat is running.
        logger.info("priority_lane_skipped", reason="disabled")
        result["skipped"] = "disabled"

    # **Unconditional, and deliberately not behind the display lane's flag.**
    # `register_token` admits every discovery to the nursery whenever the
    # capacity setting allows it, and this pass is the only code that ever
    # takes a token *out* — by age, or by the capacity trim. Gating the two on
    # different switches meant flipping `FEATURE_PRIORITY_ENRICHMENT_ENABLED`
    # off (its purpose as an incident lever) left admission running with
    # enforcement stopped: the lane would grow without bound and never expire,
    # which is precisely the backlog it exists to escape.
    #
    # It also runs at capacity zero, because that is how the lane is drained:
    # the trim's OFFSET 0 demotes every member. Skipping the call would strand
    # whoever was already inside, outranking the whole normal population
    # indefinitely.
    #
    # Its own transaction, after the display lane, so a nursery failure can
    # never cost the display lane its refresh.
    async with SessionFactory() as session:
        nursery = await refresh_nursery_lane(session, now=datetime.now(UTC))
        await session.commit()
    # Logged even when nothing moved, for the same reason as the requeue beat:
    # a quiet maintenance pass and a dead one look identical otherwise.
    logger.info("nursery_lane_refreshed", **nursery.as_dict())
    result["nursery"] = dict(nursery.as_dict())

    return result

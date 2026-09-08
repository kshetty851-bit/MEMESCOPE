"""The Social Lab's beat. Contained, locked, dark by default.

The fourth registry to run on the Compound Lab's service. That is the point of
having parameterised it: the banking arithmetic, and the rule that makes it
honest — compound from what was REALISED, never from the target — exist once
and are now shared by four experiments.

Its own advisory lock, in the shared namespace. Each wallet banks
independently and a banking is a read-modify-write on that wallet's cash, so
two overlapping ticks could pay one cycle out twice. The unique index on
(strategy_row_id, cycle_no) would catch the second write, but only after the
first had already credited the money.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.compound.service import CompoundService
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.social import spec as mspec
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

SOCIAL_LAB_LOCK_KEY = 0x534F434C


@celery_app.task(name="app.social.scheduler.social_tick")
def social_tick() -> dict[str, Any]:
    """Judge, settle, then test both wallets against their targets.

    Expect it to open NOTHING for the first hour or so. `social_reply_velocity`
    needs two readings of the same coin ten minutes apart and is None until it
    has them, so `SOC-01` cannot fire and `SOC-02` only sees coins the
    collector has already surfaced. An idle start is the rule refusing to guess,
    not a fault.
    """
    return run_async(_social_tick())


async def _social_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_SOCIAL_LAB_ENABLED", False):
        return {"skipped": "social_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, SOCIAL_LAB_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "social_already_running"}
            outcome = await CompoundService(session, registry=mspec).tick(
                now=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception("social_tick_failed")
        return {"failed": True}
    if outcome.get("banked"):
        logger.info("social_tick", banked=len(outcome["banked"]))
    return outcome

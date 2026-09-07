"""The Depth Lab's beat. Contained, locked, dark by default.

The third registry to run on the Compound Lab's service. That is the point of
having parameterised it: the banking arithmetic, and the rule that makes it
honest — compound from what was REALISED, never from the target — exist once
and are now shared by three experiments.

Its own advisory lock, in the shared namespace. Twenty wallets bank
independently and each banking is a read-modify-write on that wallet's cash, so
two overlapping ticks could pay one cycle out twice. The unique index on (strategy_row_id, cycle_no) would catch the
second write, but only after the first had already credited the money.
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
from app.depth import spec as mspec
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

DEPTH_LOCK_KEY = 0x44505448


@celery_app.task(name="app.depth.scheduler.depth_tick")
def depth_tick() -> dict[str, Any]:
    """Judge, settle, then test all twenty depth cells against their targets."""
    return run_async(_depth_tick())


async def _depth_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_DEPTH_LAB_ENABLED", False):
        return {"skipped": "depth_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, DEPTH_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "depth_already_running"}
            outcome = await CompoundService(session, registry=mspec).tick(
                now=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception("depth_tick_failed")
        return {"failed": True}
    if outcome.get("banked"):
        logger.info("depth_tick", banked=len(outcome["banked"]))
    return outcome

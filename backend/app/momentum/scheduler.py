"""Momentum V2's beat. Contained, locked, dark by default.

Reuses the Compound Lab's service over this registry rather than owning a
second copy of the banking arithmetic — the rule that decides whether the whole
idea is honest (compound from what was REALISED, never from the target) should
exist once.

Its own advisory lock. Twenty wallets bank independently, and each banking is a
read-modify-write on that wallet's cash; two overlapping ticks could pay a cycle
out twice. The unique index on (strategy_row_id, cycle_no) would catch the
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
from app.momentum import spec as mspec
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

MOMENTUM_LOCK_KEY = 0x4D4F4D32


@celery_app.task(name="app.momentum.scheduler.momentum_tick")
def momentum_tick() -> dict[str, Any]:
    """Judge, settle, then test all twenty wallets against their targets."""
    return run_async(_momentum_tick())


async def _momentum_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_MOMENTUM_LAB_ENABLED", False):
        return {"skipped": "momentum_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, MOMENTUM_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "momentum_already_running"}
            outcome = await CompoundService(session, registry=mspec).tick(
                now=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception("momentum_tick_failed")
        return {"failed": True}
    if outcome.get("banked"):
        logger.info("momentum_tick", banked=len(outcome["banked"]))
    return outcome

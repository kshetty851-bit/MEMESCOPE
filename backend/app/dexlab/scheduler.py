"""The Dex Lab's beat. Contained, locked, dark by default.

The eleventh registry to run on the Compound Lab's service — with its ratchet
switched off, which that service supports by parameter. The banking arithmetic
and the rule that keeps it honest exist once and are shared; only the rules
differ.

Its own advisory lock in the shared namespace, so an overlapping tick cannot
double-credit a wallet through a read-modify-write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.compound.service import CompoundService
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.dexlab import spec as dxspec
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

DEX_LAB_LOCK_KEY = 0x44455801


@celery_app.task(name="app.dexlab.scheduler.dex_tick")
def dex_tick() -> dict[str, Any]:
    """Judge, settle, and hold. Nothing banks here — the ratchet is off.

    Expect DEX-01 to be idle for stretches: only ~3.8 tokens an hour cleared
    the turnover floor in the measurement, against a control that fires on
    nearly every candidate it is offered. Compare EQUITY, never activity.
    """
    return run_async(_dex_tick())


async def _dex_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_DEX_LAB_ENABLED", False):
        return {"skipped": "dex_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, DEX_LAB_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "dex_already_running"}
            outcome = await CompoundService(session, registry=dxspec).tick(
                now=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception("dex_tick_failed")
        return {"failed": True}
    return outcome

"""CPY-02's beat. Contained, locked, dark by default.

Runs AFTER the pumpfun tick in the same minute rather than alongside it — it
consumes `pumpfun_signals`, so a control that ran first would mirror the
previous minute's trades and quietly add a minute of lag to every control
entry. The lag would be small and entirely invisible in the record, which is
exactly the kind of difference that makes a control useless.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.copycontrol.service import CopyControlService
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

COPYCONTROL_LOCK_KEY = 0x43505932


@celery_app.task(name="app.copycontrol.scheduler.copycontrol_tick")
def copycontrol_tick() -> dict[str, Any]:
    """Mirror whatever CPY-01 did since the last tick, with a random token."""
    return run_async(_copycontrol_tick())


async def _copycontrol_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_COPYCONTROL_ENABLED", False):
        return {"skipped": "copycontrol_disabled"}
    # Pointless without the arm it is a control FOR, and worse than pointless:
    # it would build a record over a period CPY-01 was not trading and invite a
    # comparison across two different windows.
    if not getattr(settings, "FEATURE_PUMPFUN_LAB_ENABLED", False):
        return {"skipped": "pumpfun_not_running"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, COPYCONTROL_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "copycontrol_already_running"}
            outcome = await CopyControlService(session).tick(
                now=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception("copycontrol_tick_failed")
        return {"failed": True}
    return outcome

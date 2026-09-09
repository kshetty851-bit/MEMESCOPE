"""The Matrix Lab's beat.

Every minute, like the other compound labs. Twenty-four wallets across two
admission streams means `evaluate_due` groups into eight (checkpoint, source)
buckets and runs one candidate query per bucket — measured at roughly 0.3s
each for the deep-AMM source, so a pass is comfortably inside the minute.
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
from app.matrix import spec as mxspec
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: "MTRX" — its own key in the shared dry-run namespace.
MATRIX_LAB_LOCK_KEY = 0x4D545258


@celery_app.task(name="app.matrix.scheduler.matrix_tick")
def matrix_tick() -> dict[str, Any]:
    """Judge, settle, then test all twenty-four wallets against their targets.

    Expect the AGED arms to open far less often than the FRESH ones: the deep
    AMMs offer about six actively-priced tokens an hour against radar's stream
    of launches. That asymmetry is the populations differing, not a fault.
    """
    return run_async(_matrix_tick())


async def _matrix_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_MATRIX_LAB_ENABLED", False):
        return {"skipped": "matrix_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, MATRIX_LAB_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "matrix_already_running"}
            outcome = await CompoundService(session, registry=mxspec).tick(
                now=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception("matrix_tick_failed")
        return {"failed": True}
    if outcome.get("banked"):
        logger.info("matrix_tick", banked=len(outcome["banked"]))
    return outcome

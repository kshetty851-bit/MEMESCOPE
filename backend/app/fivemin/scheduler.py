"""The Five-Minute Lab's beat.

Reuses `CompoundService` rather than copying the ratchet. That service already
takes a registry, and the banking arithmetic — compound from what was REALISED,
never from the target — is the number that decides whether the whole idea is
honest. A second copy of it would drift, and the drift would be invisible
because both copies would keep producing plausible figures.

Its own advisory lock, in the Lab's namespace, for the reason the Compound
Lab's exists: a cycle close credits the wallet with a read-modify-write, and
two overlapping ticks banking one cycle would compound money never earned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.compound.service import CompoundService
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.fivemin import spec as fmspec
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: Its own key, so it cannot collide with the Lab tick, the sellability sweep,
#: the Compound Lab or the PumpFun follower. "FIVE" in hex-ish ASCII.
FIVEMIN_LOCK_KEY = 0x4656454D


@celery_app.task(name="app.fivemin.scheduler.fivemin_tick")
def fivemin_tick() -> dict[str, Any]:
    """Judge, settle at five minutes, and test the wallet against its cycle."""
    return run_async(_fivemin_tick())


async def _fivemin_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_FIVEMIN_LAB_ENABLED", False):
        return {"skipped": "fivemin_disabled"}
    now = datetime.now(UTC)
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, FIVEMIN_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "fivemin_already_running"}
            outcome = await CompoundService(session, registry=fmspec).tick(now=now)
            await session.commit()
    except Exception:
        logger.exception("fivemin_tick_failed")
        return {"failed": True}
    if outcome.get("banked"):
        logger.info("fivemin_tick", **outcome)
    return outcome

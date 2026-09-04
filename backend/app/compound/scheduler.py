"""The Compound Lab's beat. Contained, like every other tick here.

A failure logs and returns rather than raising into the beat, so a problem in
this tournament cannot stop the ones running beside it — the rule the Arena,
the Lab and the research collectors all follow.

Its own advisory lock for the same reason `lab_tick` has one: a cycle close
credits cash to the wallet row with a read-modify-write, and two overlapping
ticks banking the same cycle would compound money that was never earned.
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
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: Its own key in the Lab's namespace, so it cannot collide with the tick or
#: the sellability sweep.
COMPOUND_LOCK_KEY = 0x434D5044


@celery_app.task(name="app.compound.scheduler.compound_tick")
def compound_tick() -> dict[str, Any]:
    """Judge, settle, and test the wallet against its cycle target."""
    return run_async(_compound_tick())


async def _compound_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_COMPOUND_LAB_ENABLED", False):
        return {"skipped": "compound_disabled"}
    now = datetime.now(UTC)
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, COMPOUND_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "compound_already_running"}
            outcome = await CompoundService(session).tick(now=now)
            await session.commit()
    except Exception:
        logger.exception("compound_tick_failed")
        return {"failed": True}
    if outcome.get("banked"):
        logger.info("compound_tick", **outcome)
    return outcome

"""The Movers Lab's beat. Contained, locked, dark by default.

The fifth registry to run on the Compound Lab's service. The banking
arithmetic — and the rule that keeps it honest, compound from what was
REALISED and never from the target — exists once and is shared.

Its own advisory lock, in the shared namespace. Each wallet banks
independently and a banking is a read-modify-write on that wallet's cash, so
two overlapping ticks could pay one cycle out twice. The unique index on
(strategy_row_id, cycle_no) would catch the second write, but only after the
first had already credited the money.

RUNS EVERY MINUTE, unlike its siblings. The signal is a five-minute
measurement against a thirty-minute hold, so a tick every five minutes would
resolve exits a fifth of a position's life late. The tick is cheap when
nothing is due — it is a checkpoint test, not a scan.
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
from app.movers import spec as mvspec
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: "MOVR" — its own key in the shared dry-run namespace.
MOVERS_LAB_LOCK_KEY = 0x4D4F5652


@celery_app.task(name="app.movers.scheduler.movers_tick")
def movers_tick() -> dict[str, Any]:
    """Judge, settle, then test both wallets against their targets.

    Expect MOV-01 to open less often than MOV-02, and that asymmetry is the
    experiment rather than a fault: the turnover floor is a filter, so the
    signal arm trades a subset of the control's pool by construction.
    """
    return run_async(_movers_tick())


async def _movers_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_MOVERS_LAB_ENABLED", False):
        return {"skipped": "movers_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, MOVERS_LAB_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "movers_already_running"}
            outcome = await CompoundService(session, registry=mvspec).tick(
                now=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception("movers_tick_failed")
        return {"failed": True}
    if outcome.get("banked"):
        logger.info("movers_tick", banked=len(outcome["banked"]))
    return outcome

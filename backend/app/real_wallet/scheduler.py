"""Serialized real-wallet beat tasks: the dry-run review, and the driver."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.events import publish_live_update
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.paper.service import utcnow
from app.real_wallet.driver import RealWalletDriver
from app.real_wallet.dry_run import RealWalletDryRunService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)
DRY_RUN_LOCK_NAMESPACE = 0x4D454D45
DRY_RUN_LOCK_KEY = 0x44525952
#: Its own key, so a driver tick and a dry-run review never block each other.
DRIVER_LOCK_KEY = 0x44525652


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_dry_run")
def real_wallet_dry_run() -> dict[str, Any]:
    return run_async(_real_wallet_dry_run())


async def _real_wallet_dry_run() -> dict[str, Any]:
    if not settings.FEATURE_REAL_WALLET_DRY_RUN_ENABLED:
        return {"skipped": "dry_run_feature_disabled"}
    if settings.REAL_WALLET_EXECUTION_MODE != "dry_run":
        return {"skipped": "execution_mode_disabled"}
    async with SessionFactory() as session:
        acquired = await session.scalar(
            select(func.pg_try_advisory_xact_lock(DRY_RUN_LOCK_NAMESPACE, DRY_RUN_LOCK_KEY))
        )
        if not acquired:
            await session.rollback()
            return {"skipped": "dry_run_already_running"}
        outcome = await RealWalletDryRunService(session).review(now=utcnow())
        await session.commit()
    await publish_live_update("real_wallet.dry_run.changed")
    logger.info("real_wallet_dry_run", **outcome.as_dict())
    return outcome.as_dict()


def request_dry_run(*, trigger: str) -> None:
    """Queue the same dry-run after Radar moves; never run inline."""
    if not settings.FEATURE_REAL_WALLET_DRY_RUN_ENABLED:
        return
    if settings.REAL_WALLET_EXECUTION_MODE != "dry_run":
        return
    try:
        real_wallet_dry_run.delay()
    except Exception:  # pragma: no cover - broker failure must not roll back Radar.
        logger.warning("real_wallet_dry_run_enqueue_failed", trigger=trigger, exc_info=True)


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_driver_tick")
def real_wallet_driver_tick() -> dict[str, Any]:
    """Give the driver a heartbeat.

    Without this nothing ever calls it: the operator could nominate a strategy,
    press START, and watch a switch that was on while no intent was ever created.

    The task adds no authority of its own. `RealWalletDriver.tick` is a chain of
    refusals — switch off, no strategy, no wallet, no entry size, kill switch,
    unreadable balance, policy bounds, no fresh decision, mint already traded —
    and the default state of the switch refuses at the first of them. Creating an
    intent is not spending: every barrier downstream of it still stands.

    Every minute, matching the Lab's beat, because a Lab decision is actionable
    for ten minutes and a slower tick would spend most of that shelf life asleep.
    """
    return run_async(_real_wallet_driver_tick())


async def _real_wallet_driver_tick() -> dict[str, Any]:
    try:
        async with SessionFactory() as session:
            # One driver at a time. The intent's idempotency key already stops a
            # duplicate row, but two concurrent ticks would each read the open
            # position count before either wrote, and the policy would be
            # counting a book that no longer exists.
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, DRIVER_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "driver_already_running"}
            outcome = await RealWalletDriver(session).tick(now=utcnow())
            await session.commit()
    except Exception:
        # Contained like the Lab's: a driver failure must not stop the beat that
        # also runs the kill switch's neighbours.
        logger.exception("real_wallet_driver_tick_failed")
        return {"failed": True}
    if outcome.created:
        logger.warning("real_wallet_driver_tick", **outcome.as_dict())
    return outcome.as_dict()

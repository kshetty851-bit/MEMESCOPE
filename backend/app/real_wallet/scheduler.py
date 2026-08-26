"""Serialized real-wallet beat tasks: the dry-run review, the driver, the runner."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.events import publish_live_update
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.paper.service import utcnow
from app.real_wallet.driver import RealWalletDriver
from app.real_wallet.dry_run import RealWalletDryRunService
from app.real_wallet.executor import RealWalletExecutor
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)
DRY_RUN_LOCK_NAMESPACE = 0x4D454D45
DRY_RUN_LOCK_KEY = 0x44525952
#: Its own key, so a driver tick and a dry-run review never block each other.
DRIVER_LOCK_KEY = 0x44525652
#: And the runner's, for the same reason.
EXECUTOR_LOCK_KEY = 0x45584543

#: States that still have somewhere to go. Terminal ones are skipped rather than
#: queried, so a finished book does not grow the work every minute.
UNFINISHED_STATES = ("created", "safety_approved", "order_created", "submitted")


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


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_executor_tick")
def real_wallet_executor_tick() -> dict[str, Any]:
    """Walk every unfinished intent forward by one state.

    The driver creates intents and nothing moved them, so an intent would sit at
    CREATED for ever. `advance` performs at most one transition per call, so an
    intent needs several ticks to reach a terminal state — which is exactly what
    makes a crash mid-flight recoverable: every state is a committed row.

    The runner owns no authority. `LiveSubmissionGuard` and
    `ExecutionTransportPolicy` decide whether anything may be submitted, and on
    mainnet both still refuse, so a complete walk today ends in a recorded
    refusal rather than a transaction.
    """
    return run_async(_real_wallet_executor_tick())


async def _real_wallet_executor_tick() -> dict[str, Any]:
    outcomes: list[dict[str, object]] = []
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, EXECUTOR_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "executor_already_running"}
            ids = list((await session.scalars(
                select(RealWalletLiveIntent.id)
                .where(RealWalletLiveIntent.state.in_(UNFINISHED_STATES))
                .order_by(RealWalletLiveIntent.created_at)
            )).all())
            executor = RealWalletExecutor(session)
            for intent_id in ids:
                # One intent's failure must not strand the rest of the book, and
                # in particular must not stop a SUBMITTED intent from being
                # reconciled — that is the one step that cannot wait.
                try:
                    outcome = await executor.advance(intent_id, now=utcnow())
                    outcomes.append(outcome.as_dict())
                except Exception:
                    logger.exception("real_wallet_advance_failed",
                                     intent_id=str(intent_id))
            await session.commit()
    except Exception:
        logger.exception("real_wallet_executor_tick_failed")
        return {"failed": True}
    advanced = [o for o in outcomes if o.get("changed")]
    if advanced:
        logger.warning("real_wallet_executor_tick", advanced=len(advanced),
                       states=[o["state"] for o in advanced])
    return {"examined": len(outcomes), "advanced": len(advanced),
            "outcomes": outcomes}

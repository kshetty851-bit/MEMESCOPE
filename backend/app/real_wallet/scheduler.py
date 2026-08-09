"""Serialized autonomous dry-run task, downstream of committed Radar state."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.events import publish_live_update
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.paper.service import utcnow
from app.real_wallet.dry_run import RealWalletDryRunService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)
DRY_RUN_LOCK_NAMESPACE = 0x4D454D45
DRY_RUN_LOCK_KEY = 0x44525952


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

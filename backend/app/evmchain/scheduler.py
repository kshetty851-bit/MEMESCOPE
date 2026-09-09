"""The EVM launch collector's beat.

Every two minutes against five pages. Five pages is about thirty-five minutes
of the feed, so a pass that fails entirely still leaves fifteen passes of
overlap before anything falls out of the seventy-minute window — the collector
is racing a window it cannot re-open, so the overlap is the point.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.evmchain import collector
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

EVM_LAUNCH_LOCK_KEY = 0x45564D4C


@celery_app.task(name="app.evmchain.scheduler.evm_launch_tick")
def evm_launch_tick() -> dict[str, Any]:
    return run_async(_tick())


async def _tick() -> dict[str, Any]:
    if not getattr(settings, "FEATURE_EVM_LAUNCHES_ENABLED", False):
        return {"skipped": "evm_launches_disabled"}
    networks = list(getattr(settings, "EVM_LAUNCH_NETWORKS", ["base"]))
    pages = int(getattr(settings, "EVM_LAUNCH_PAGES", 5))
    out: dict[str, Any] = {}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, EVM_LAUNCH_LOCK_KEY))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "evm_launches_already_running"}
            now = datetime.now(UTC)
            for network in networks:
                out[network] = await collector.discover(
                    session, network=network, pages=pages, now=now)
            await session.commit()
    except Exception:
        logger.exception("evm_launch_tick_failed")
        return {"failed": True}
    if any(v.get("stamped") for v in out.values()):
        logger.info("evm_launch_tick", **{k: v["stamped"] for k, v in out.items()})
    return out

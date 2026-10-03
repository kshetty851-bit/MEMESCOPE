"""The Meme Lifecycle Lab's beat. Dark by default, locked, sessions owned here.

Every task returns before opening a session while
``FEATURE_LIFECYCLE_LAB_ENABLED`` is off, so registering the beat entries in
``app/workers/celery_app.py`` starts nothing.

Each task holds its own transaction-scoped advisory lock in the shared
namespace, so an overlapping tick (a slow collection, a retried replay) skips
rather than running twice. Sessions are opened, committed and closed here —
the service only flushes.

| task                            | cadence      | what                                   |
|---------------------------------|--------------|----------------------------------------|
| ``lifecycle_collect_tick``      | every 15 min | FORWARD collection, one commit/source  |
| ``lifecycle_detect_events_tick``| every 5 min  | forward event detection at the grid    |
| ``lifecycle_timeliness_tick``   | every 15 min | settle event outcomes after 26h        |
| ``lifecycle_forward_replay_tick``| every 30 min| AUTHORITATIVE replay, re-saved per arm |
| ``lifecycle_autolink_tick``     | hourly       | DexScreener search → ≥0.8 links only   |
| ``lifecycle_experiment_tick``   | hourly       | register / refresh the experiment set  |
| ``lifecycle_backfill``          | on demand    | EXPLORATORY backfill (admin POST)      |
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.lifecycle_lab.adapters import DexScreenerAdapter
from app.lifecycle_lab.service import LifecycleLabService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: One key per task, in the shared namespace ("MLL" + a task digit).
LOCK_COLLECT = 0x4D4C4C01
LOCK_AUTOLINK = 0x4D4C4C02
LOCK_EVENTS = 0x4D4C4C03
LOCK_TIMELINESS = 0x4D4C4C04
LOCK_REPLAY = 0x4D4C4C05
LOCK_EXPERIMENT = 0x4D4C4C06
LOCK_BACKFILL = 0x4D4C4C07

#: Outbound client for the third-party sources. Adapters set per-request
#: timeouts; this is only a ceiling.
HTTP_TIMEOUT_SECONDS = 30.0


def _now() -> datetime:
    return datetime.now(UTC)


async def _locked(session: AsyncSession, key: int) -> bool:
    return bool(
        await session.scalar(
            select(func.pg_try_advisory_xact_lock(DRY_RUN_LOCK_NAMESPACE, key))
        )
    )


async def _run_locked(
    name: str,
    key: int,
    body: Callable[[LifecycleLabService], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    if not settings.FEATURE_LIFECYCLE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    try:
        async with SessionFactory() as session:
            if not await _locked(session, key):
                await session.rollback()
                return {"skipped": f"{name}_already_running"}
            outcome = await body(LifecycleLabService(session))
            await session.commit()
    except Exception:
        logger.exception(f"lifecycle_{name}_failed")
        return {"failed": True}
    logger.info(f"lifecycle_{name}", **{k: v for k, v in outcome.items() if k != "runs"})
    return outcome


# --------------------------------------------------------------------------
# Collection — one transaction per source
# --------------------------------------------------------------------------


@celery_app.task(name="app.lifecycle_lab.scheduler.lifecycle_collect_tick")
def lifecycle_collect_tick() -> dict[str, Any]:
    return run_async(_collect_tick())


async def _collect_tick() -> dict[str, Any]:
    """One FORWARD pass, committed per source: a slow or failing source
    (GDELT's 6s spacing) cannot roll back the rows a fast one already wrote.
    The lock is re-taken per source so a concurrent tick still skips."""
    if not settings.FEATURE_LIFECYCLE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    now = _now()
    statuses: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        adapters = LifecycleLabService.build_adapters(client)
        for adapter in sorted(adapters, key=lambda a: a.source.value):
            try:
                async with SessionFactory() as session:
                    if not await _locked(session, LOCK_COLLECT):
                        await session.rollback()
                        return {"skipped": "collect_already_running", "sources": statuses}
                    runs = await LifecycleLabService(session).collect(
                        now, [adapter], clock=_now
                    )
                    await session.commit()
            except Exception:
                logger.exception("lifecycle_collect_failed", source=adapter.source.value)
                statuses[adapter.source.value] = "failed"
                continue
            for run in runs:
                if run.meme_id is None and run.mint_address is None:
                    statuses[run.source.value] = run.status.value
    logger.info("lifecycle_collect", **statuses)
    return {"sources": statuses}


# --------------------------------------------------------------------------
# Linking, detection, outcomes, replay, registry
# --------------------------------------------------------------------------


@celery_app.task(name="app.lifecycle_lab.scheduler.lifecycle_autolink_tick")
def lifecycle_autolink_tick() -> dict[str, Any]:
    return run_async(_autolink_tick())


async def _autolink_tick() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        adapter = DexScreenerAdapter(settings, client)

        async def body(service: LifecycleLabService) -> dict[str, Any]:
            return await service.autolink(_now(), adapter, clock=_now)

        return await _run_locked("autolink", LOCK_AUTOLINK, body)


@celery_app.task(name="app.lifecycle_lab.scheduler.lifecycle_detect_events_tick")
def lifecycle_detect_events_tick() -> dict[str, Any]:
    return run_async(
        _run_locked("detect_events", LOCK_EVENTS, lambda s: s.detect_and_store_events(_now()))
    )


@celery_app.task(name="app.lifecycle_lab.scheduler.lifecycle_timeliness_tick")
def lifecycle_timeliness_tick() -> dict[str, Any]:
    return run_async(
        _run_locked("timeliness", LOCK_TIMELINESS, lambda s: s.fill_timeliness(_now()))
    )


@celery_app.task(name="app.lifecycle_lab.scheduler.lifecycle_forward_replay_tick")
def lifecycle_forward_replay_tick() -> dict[str, Any]:
    return run_async(
        _run_locked("forward_replay", LOCK_REPLAY, lambda s: s.run_forward_replay(_now()))
    )


@celery_app.task(name="app.lifecycle_lab.scheduler.lifecycle_experiment_tick")
def lifecycle_experiment_tick() -> dict[str, Any]:
    async def body(service: LifecycleLabService) -> dict[str, Any]:
        ids = await service.ensure_baseline_experiment(_now())
        return {"experiments": len(ids)}

    return run_async(_run_locked("experiment", LOCK_EXPERIMENT, body))


@celery_app.task(name="app.lifecycle_lab.scheduler.lifecycle_backfill")
def lifecycle_backfill(slug: str, start: str, end: str) -> dict[str, Any]:
    return run_async(
        _backfill(slug, datetime.fromisoformat(start), datetime.fromisoformat(end))
    )


async def _backfill(slug: str, start: datetime, end: datetime) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:

        async def body(service: LifecycleLabService) -> dict[str, Any]:
            runs = await service.backfill(slug, _now(), start, end, client, clock=_now)
            return {
                "slug": slug,
                "runs": [
                    {
                        "source": r.source.value,
                        "status": r.status.value,
                        "reason": r.reason,
                        "observations_written": r.observations_written,
                    }
                    for r in runs
                    if r.meme_id is None and r.mint_address is None
                ],
            }

        return await _run_locked("backfill", LOCK_BACKFILL, body)

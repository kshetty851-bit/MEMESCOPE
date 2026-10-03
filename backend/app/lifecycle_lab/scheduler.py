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
| ``lifecycle_collect_tick``      | every 15 min | FORWARD collection, one commit/source; |
|                                 |              | who is asked: ``priority.py`` plan     |
| ``lifecycle_detect_events_tick``| every 5 min  | forward event detection at the grid    |
| ``lifecycle_timeliness_tick``   | every 15 min | settle event outcomes after 26h        |
| ``lifecycle_forward_replay_tick``| every 30 min| AUTHORITATIVE replay per arm, resumed |
|                                 |              | from its checkpoint when still valid   |
| ``lifecycle_autolink_tick``     | hourly       | DexScreener search → ≥0.8 links only   |
| ``lifecycle_experiment_tick``   | hourly       | register / refresh the experiment set  |
| ``lifecycle_backfill``          | on demand    | EXPLORATORY backfill (admin POST)      |
"""

from __future__ import annotations

import time
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
from app.lifecycle_lab import priority
from app.lifecycle_lab.adapters import DexScreenerAdapter
from app.lifecycle_lab.collector import SourceSchedule
from app.lifecycle_lab.domain import Source
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

#: Seconds of the collect task's hard limit NOT spent on spaced GDELT requests:
#: planning, Wikipedia, DexScreener, DB writes and a slow GDELT answer or two.
#: The GDELT adapter also refuses to start a request that could run past
#: (limit - margin), so a run of slow answers defers memes instead of the task
#: being killed mid-write.
COLLECT_MARGIN_SECONDS = 180.0
#: Fallback if the Celery config carries no hard limit.
DEFAULT_TASK_TIME_LIMIT_SECONDS = 600.0


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
    deadline = time.monotonic() + max(0.0, _task_time_limit() - COLLECT_MARGIN_SECONDS)
    statuses: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        adapters = LifecycleLabService.build_adapters(client)
        schedule: dict[Source, SourceSchedule] | None
        try:
            async with SessionFactory() as session:
                schedule = await LifecycleLabService(session).plan_collection(
                    now, adapters, gdelt_budget=gdelt_budget(), gdelt_deadline=deadline
                )
                await session.rollback()
        except Exception:
            # Unscheduled is the pre-scheduler behaviour (every subject, fixed
            # span): bounded for the 10-20 memes this targets, and better than
            # collecting nothing. Logged loudly, never silent.
            logger.exception("lifecycle_collect_plan_failed")
            schedule = None
        for adapter in sorted(adapters, key=lambda a: a.source.value):
            try:
                async with SessionFactory() as session:
                    if not await _locked(session, LOCK_COLLECT):
                        await session.rollback()
                        return {"skipped": "collect_already_running", "sources": statuses}
                    runs = await LifecycleLabService(session).collect(
                        now, [adapter], clock=_now, schedule=schedule
                    )
                    await session.commit()
            except Exception:
                logger.exception("lifecycle_collect_failed", source=adapter.source.value)
                statuses[adapter.source.value] = "failed"
                continue
            if not runs and schedule is not None and adapter.source in schedule:
                statuses[adapter.source.value] = "not_due"
            for run in runs:
                if run.meme_id is None and run.mint_address is None:
                    statuses[run.source.value] = run.status.value
    logger.info("lifecycle_collect", **statuses)
    out: dict[str, Any] = {"sources": statuses}
    if schedule is not None:
        out["schedule"] = {s.value: p.summary for s, p in sorted(schedule.items())}
    else:
        out["schedule"] = "unscheduled"
    return out


def _task_time_limit() -> float:
    return float(celery_app.conf.task_time_limit or DEFAULT_TASK_TIME_LIMIT_SECONDS)


def gdelt_budget() -> int:
    """GDELT requests one collect pass may make:
    floor((task_time_limit - COLLECT_MARGIN_SECONDS) / MLL_GDELT_MIN_INTERVAL_SECONDS).
    With the defaults (600 s, 180 s, 6 s) that is 70 - far above the 10-20
    memes the Lab targets, so the budget only bites if tracking grows."""
    return priority.gdelt_request_budget(
        _task_time_limit(), COLLECT_MARGIN_SECONDS, settings.MLL_GDELT_MIN_INTERVAL_SECONDS
    )


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
    return run_async(_run_locked("forward_replay", LOCK_REPLAY, _forward_replay))


async def _forward_replay(service: LifecycleLabService) -> dict[str, Any]:
    """Each arm resumes from its checkpoint when it may (see
    ``LifecycleLabService.run_forward_replay``). Whether it did, and why not,
    is logged per arm — a checkpoint invalidated every run is a cost leak
    worth seeing (late-arriving rows behind the safety lag, usually)."""
    out = await service.run_forward_replay(_now())
    for arm, run in (out.get("runs") or {}).items():
        logger.info(
            "lifecycle_forward_replay_arm",
            arm=arm,
            replay=run.get("replay"),
            invalidation_reason=run.get("invalidation_reason"),
            ticks_processed=run.get("ticks_processed"),
        )
    return out


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

"""What the production watch can actually measure, and nothing else.

── THE RULE ─────────────────────────────────────────────────────────────

Every probe below is wrapped so that a failure becomes `unknown` with the
error attached, never an absent row and never a healthy one. That is not
defensive coding for its own sake: this endpoint is the evidence behind a
cartoon character standing at a monitoring wall, and a character who looks
calm because a probe threw is the single most expensive bug this feature can
have.

── WHY THE THRESHOLDS ARE NOT LOCAL ─────────────────────────────────────

Disk thresholds come from `settings`, the same values `check_disk_space` acts
on. If HQ kept its own copy, the room could show amber while the retention
task considered the disk fine, or worse the reverse — and the number a person
reads would not be the number the system acts on.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.hq_ops import task_outcomes
from app.hq_ops.schemas import (
    ComponentHealth,
    ComponentStatus,
    DiskHealth,
    OperationsHealth,
    QueueHealth,
    LabHealthRow,
    WalletHealthRow,
    SchedulerHealth,
    TaskOutcome,
    WorkerHealth,
)

logger = get_logger(__name__)

#: Ordered worst-last, so `max` over this picks the worse status.
#: `unknown` sits below `healthy` on purpose — see `_roll_up`, which excludes
#: it entirely rather than letting an unmeasured component win or lose.
_SEVERITY: dict[ComponentStatus, int] = {
    "unknown": -1,
    "healthy": 0,
    "degraded": 1,
    "down": 2,
}

#: How long the worker control channel is given to answer. Generous: a busy
#: prefork worker replies in milliseconds, and the cost of being impatient
#: here is declaring a healthy worker dead.
WORKER_PING_TIMEOUT = 3.0

#: Beat writes its heartbeat every minute (see `celery_app.beat_schedule`).
#: Three misses before this degrades — the same "one missed tick is not an
#: outage" reasoning the pipeline health windows use.
BEAT_EXPECTED_WITHIN_SECONDS = 200.0

#: Depth at which a queue is reported as backed up rather than busy. A
#: presentation threshold, and labelled as one: nothing downstream treats it
#: as a fault, it only decides whether the row reads amber.
QUEUE_DEGRADED_DEPTH = 500

#: The broker lists this queue by default; the workers declare no others.
BROKER_QUEUES = ("celery",)


def beat_heartbeat_key() -> str:
    """Where the scheduler publishes that it is still firing."""
    return f"{settings.redis_namespace}:memescope:hq:beat"


async def _probe_disk() -> DiskHealth:
    warning = settings.DISK_WARNING_PERCENT
    critical = settings.DISK_CRITICAL_PERCENT
    try:
        total, used, _free = await asyncio.to_thread(shutil.disk_usage, "/")
        percent = round(used / total * 100, 1) if total else 0.0
    except Exception as exc:
        logger.warning("hq_disk_probe_failed", error=str(exc))
        return DiskHealth(
            status="unknown",
            percent_used=None,
            warning_percent=warning,
            critical_percent=critical,
            measured=False,
            detail=f"Disk usage could not be read: {exc}",
        )

    if percent >= critical:
        status: ComponentStatus = "down"
    elif percent >= warning:
        status = "degraded"
    else:
        status = "healthy"
    return DiskHealth(
        status=status,
        percent_used=percent,
        warning_percent=warning,
        critical_percent=critical,
        detail=f"{percent}% of the volume used.",
    )


async def _probe_redis() -> ComponentHealth:
    started = time.perf_counter()
    try:
        await get_redis().ping()
    except Exception as exc:
        logger.warning("hq_redis_probe_failed", error=str(exc))
        return ComponentHealth(
            component="redis",
            status="down",
            detail=f"Redis did not answer a ping: {exc}",
            measured=True,
        )
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    return ComponentHealth(
        component="redis",
        status="healthy",
        detail="Broker answered a ping.",
        latency_ms=elapsed,
    )


async def _probe_database(session: AsyncSession) -> ComponentHealth:
    started = time.perf_counter()
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("hq_database_probe_failed", error=str(exc))
        return ComponentHealth(
            component="database",
            status="down",
            detail=f"Database did not answer a query: {exc}",
            measured=True,
        )
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    return ComponentHealth(
        component="database",
        status="healthy",
        detail="Database answered a query.",
        latency_ms=elapsed,
    )


def _ping_workers() -> list[dict[str, Any]]:
    """Blocking Celery control ping. Called via a thread — see `_probe_worker`.

    Broadcast rather than scoped, unlike the container healthcheck: this asks
    "is *any* worker consuming", which is the question HQ needs. The container
    probe asks the different question of whether one specific worker is alive,
    and it is right for it to be scoped and right for this not to be.
    """
    from app.workers.celery_app import celery_app

    return celery_app.control.ping(timeout=WORKER_PING_TIMEOUT) or []


async def _probe_worker() -> WorkerHealth:
    try:
        replies = await asyncio.to_thread(_ping_workers)
    except Exception as exc:
        logger.warning("hq_worker_probe_failed", error=str(exc))
        return WorkerHealth(
            status="unknown",
            nodes=[],
            replies=0,
            measured=False,
            detail=f"The worker control channel could not be reached: {exc}",
        )

    nodes = sorted(name for reply in replies for name in reply)
    if not nodes:
        return WorkerHealth(
            status="down",
            nodes=[],
            replies=0,
            detail="No worker answered the control ping.",
        )
    return WorkerHealth(
        status="healthy",
        nodes=nodes,
        replies=len(nodes),
        detail=f"{len(nodes)} worker{'' if len(nodes) == 1 else 's'} answered a ping.",
    )


async def _probe_scheduler(*, now: datetime) -> SchedulerHealth:
    try:
        raw = await get_redis().get(beat_heartbeat_key())
    except Exception as exc:
        logger.warning("hq_scheduler_probe_failed", error=str(exc))
        return SchedulerHealth(
            status="unknown",
            last_beat=None,
            seconds_since_beat=None,
            expected_within_seconds=BEAT_EXPECTED_WITHIN_SECONDS,
            measured=False,
            detail=f"The scheduler heartbeat could not be read: {exc}",
        )

    if not raw:
        # No key is genuinely ambiguous: beat has stopped, or it has never run
        # since this feature shipped, or the key expired during a long gap.
        # `unknown` rather than `down`, and the sentence says which is which.
        return SchedulerHealth(
            status="unknown",
            last_beat=None,
            seconds_since_beat=None,
            expected_within_seconds=BEAT_EXPECTED_WITHIN_SECONDS,
            measured=False,
            detail="The scheduler has published no heartbeat.",
        )

    try:
        payload = json.loads(raw)
        last = datetime.fromisoformat(str(payload["at"]))
    except (ValueError, TypeError, KeyError) as exc:
        return SchedulerHealth(
            status="unknown",
            last_beat=None,
            seconds_since_beat=None,
            expected_within_seconds=BEAT_EXPECTED_WITHIN_SECONDS,
            measured=False,
            detail=f"The scheduler heartbeat was unreadable: {exc}",
        )

    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    age = round((now - last).total_seconds(), 1)
    status: ComponentStatus = "healthy" if age <= BEAT_EXPECTED_WITHIN_SECONDS else "down"
    return SchedulerHealth(
        status=status,
        last_beat=last,
        seconds_since_beat=age,
        expected_within_seconds=BEAT_EXPECTED_WITHIN_SECONDS,
        detail=f"Last scheduler beat {age:.0f}s ago.",
    )


async def _probe_queues() -> QueueHealth:
    try:
        redis = get_redis()
        depths = {name: int(await redis.llen(name)) for name in BROKER_QUEUES}
    except Exception as exc:
        logger.warning("hq_queue_probe_failed", error=str(exc))
        return QueueHealth(
            status="unknown",
            depths={},
            total=None,
            measured=False,
            detail=f"Queue depth could not be read: {exc}",
        )

    total = sum(depths.values())
    status: ComponentStatus = "degraded" if total >= QUEUE_DEGRADED_DEPTH else "healthy"
    return QueueHealth(
        status=status,
        depths=depths,
        total=total,
        detail=f"{total} message{'' if total == 1 else 's'} waiting on the broker.",
    )


def _roll_up(statuses: list[ComponentStatus]) -> ComponentStatus:
    """Worst status across everything that was *measured*.

    Unmeasured components are excluded rather than counted either way. Letting
    them win would make the roll-up permanently unknown the moment one probe
    is unavailable; letting them lose would hide a real outage behind four
    green rows. They are reported on their own row and counted in `unmeasured`,
    which is where a reader can actually act on them.
    """
    measured = [status for status in statuses if status != "unknown"]
    if not measured:
        return "unknown"
    return max(measured, key=lambda status: _SEVERITY[status])


async def _probe_lab(now: datetime) -> LabHealthRow:
    """The Strategy Lab's evidence quality, asked of the Lab itself.

    `app.lab.health` owns the semantics — what stale means, which tournament is
    current, how a mark is backed — because those are the Lab's rules and a
    second copy here would drift from them.

    ITS OWN SESSION, deliberately. The probes run concurrently and a SQLAlchemy
    session is not safe for concurrent use: sharing the caller's put this probe
    and `_probe_database` on the same connection, and the first snapshot after
    it shipped failed with "concurrent operations are not permitted" — reported
    honestly as unmeasured, but measuring nothing.
    """
    from app.db.session import SessionFactory
    from app.lab.health import read as read_lab

    try:
        async with SessionFactory() as session:
            reading = await read_lab(session, now=now)
        return LabHealthRow(**reading.as_dict())
    except Exception as exc:  # noqa: BLE001
        logger.warning("hq_lab_probe_failed", error=str(exc))
        return LabHealthRow(measured=False, detail=f"Lab health probe failed: {exc}")



async def _probe_compound(now: datetime) -> LabHealthRow:
    """The Compound Lab, measured by the same rules as the Lab.

    A second tournament runs on these tables and every signal means the same
    thing for it — a frozen book, a halted tick, silence where decisions should
    be. `app.lab.health.read` takes the registry, so this is the same
    measurement rather than a second copy that would drift.

    Its own session for the same concurrency reason as `_probe_lab`.
    """
    from app.compound import spec as cspec
    from app.db.session import SessionFactory
    from app.lab.health import read as read_lab

    try:
        async with SessionFactory() as session:
            reading = await read_lab(session, now=now, registry=cspec)
        return LabHealthRow(**reading.as_dict())
    except Exception as exc:  # noqa: BLE001
        logger.warning("hq_compound_probe_failed", error=str(exc))
        return LabHealthRow(
            measured=False, detail=f"Compound Lab health probe failed: {exc}")


async def _probe_wallet(now: datetime) -> WalletHealthRow:
    """The execution rail, asked of the wallet's own module.

    Its own session for the same reason as the Lab probe: these run under
    `asyncio.gather` and a SQLAlchemy session is not safe for concurrent use.
    """
    from app.db.session import SessionFactory
    from app.real_wallet.wallet_health import read as read_wallet

    try:
        async with SessionFactory() as session:
            reading = await read_wallet(session, now=now)
        return WalletHealthRow(**reading.as_dict())
    except Exception as exc:  # noqa: BLE001
        logger.warning("hq_wallet_probe_failed", error=str(exc))
        return WalletHealthRow(measured=False, detail=f"Wallet probe failed: {exc}")


async def snapshot(session: AsyncSession, *, now: datetime | None = None) -> OperationsHealth:
    """One reading of every component. Probes run concurrently.

    Concurrently because the worker ping alone can take three seconds, and a
    monitoring endpoint that takes six is one nobody polls often enough for it
    to be monitoring.
    """
    moment = now or datetime.now(UTC)
    (disk, redis_health, database, worker, scheduler, queues, task_rows,
     lab_row, compound_row, wallet_row) = await asyncio.gather(
        _probe_disk(),
        _probe_redis(),
        _probe_database(session),
        _probe_worker(),
        _probe_scheduler(now=moment),
        _probe_queues(),
        task_outcomes.read_all(),
        _probe_lab(moment),
        _probe_compound(moment),
        _probe_wallet(moment),
    )

    parts: list[ComponentStatus] = [
        disk.status,
        redis_health.status,
        database.status,
        worker.status,
        scheduler.status,
        queues.status,
    ]
    unmeasured = sum(
        0 if measured else 1
        for measured in (
            disk.measured,
            redis_health.measured,
            database.measured,
            worker.measured,
            scheduler.measured,
            queues.measured,
        )
    )

    return OperationsHealth(
        disk=disk,
        redis=redis_health,
        database=database,
        worker=worker,
        scheduler=scheduler,
        queues=queues,
        # Reported beside the components but deliberately NOT folded into
        # `overall`. A failing task is a fault in the platform's WORK; `overall`
        # is a verdict on its INFRASTRUCTURE, and merging them would make a
        # broken Lab sweep look like a sick database to anyone reading the top
        # line. They are different questions and they get different rows.
        tasks=[TaskOutcome(**row) for row in task_rows],
        tasks_failing=len(task_outcomes.failing(task_rows)),
        lab=lab_row,
        compound=compound_row,
        wallet=wallet_row,
        overall=_roll_up(parts),
        unmeasured=unmeasured,
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
        observed_at=moment,
    )

"""The scheduler's proof of life.

Beat has no control channel. It only sends, so nothing can ask it whether it
is still running, and it lives in a container the API cannot see into. The
worker healthcheck's own docstring records what that cost once: beat "happily
queued tasks nobody ran" for fifty minutes while its container reported a
status that had been meaningless for weeks.

So beat writes down that it fired. One key, one timestamp, a TTL longer than
the gap that would count as an outage. If the schedule stops turning, the key
stops advancing and then expires, and `_probe_scheduler` can tell the
difference between a scheduler that is late and one that is gone.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.hq_ops.probe import beat_heartbeat_key
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: Comfortably longer than the degraded window, so the key survives a few
#: missed ticks and its *absence* means something stronger than lateness.
HEARTBEAT_TTL_SECONDS = 900


@celery_app.task(name="app.hq_ops.tasks.publish_beat_heartbeat")
def publish_beat_heartbeat() -> dict[str, str]:
    """Record that the scheduler fired. Never raises.

    A heartbeat that can fail the beat process would be a monitoring feature
    that causes the outage it watches for.
    """
    return run_async(_publish())


async def _publish() -> dict[str, str]:
    at = datetime.now(UTC).isoformat()
    try:
        # `run_async` owns the Redis lifecycle for every Celery task here, so
        # this opens nothing and closes nothing.
        await get_redis().set(
            beat_heartbeat_key(),
            json.dumps({"at": at}),
            ex=HEARTBEAT_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning("hq_beat_heartbeat_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}
    return {"status": "ok", "at": at}


@celery_app.task(name="app.hq_ops.tasks.hq_ops_tick")
def hq_ops_tick() -> dict[str, Any]:
    """The autonomous pass: detect, open incidents, repair what is permitted.

    Runs on the worker rather than in the API, for the same reason the prune
    does: it opens database sessions, waits on a control channel, and can sleep
    for seconds at a time. None of that belongs in a request pool.

    Never raises. A monitoring loop that can crash its own worker is a
    monitoring loop that causes the outage it watches for — the failure is
    logged and the next tick tries again.
    """
    return run_async(_tick())


async def _tick() -> dict[str, Any]:
    from app.db.session import SessionFactory
    from app.hq_ops.service import tick

    try:
        async with SessionFactory() as session:
            return await tick(session)
    except Exception as exc:
        logger.exception("hq_ops_tick_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}


@celery_app.task(name="app.hq_ops.tasks.karthik_ops_tick")
def karthik_ops_tick() -> dict[str, Any]:
    """Karthik's observation pass, on the same beat as HQ's own.

    Filed here rather than in a `karthik_ops.tasks` of its own because §26 is
    explicit that there is one scheduler, and the argument extends to the task
    registry: a second module registering a second periodic task against the
    same beat is two places to look when the schedule misbehaves.

    What it *does* is entirely Karthik's, and it is one call into his own
    service. Under OBSERVE_ONLY it records and executes nothing.

    Never raises, for the same reason as `hq_ops_tick`.
    """
    return run_async(_karthik_tick())


async def _karthik_tick() -> dict[str, Any]:
    from app.db.session import SessionFactory
    from app.karthik_ops.service import tick

    try:
        async with SessionFactory() as session:
            return await tick(session)
    except Exception as exc:
        logger.exception("karthik_ops_tick_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}

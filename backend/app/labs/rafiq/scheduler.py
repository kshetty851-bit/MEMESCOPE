"""The lab's beat task. Registered in `app/workers/celery_app.py`, every minute.

Every minute, like the V6 Lab and the Arena, because Strategy B's exits are
measured in a two-hour box and a coarser beat would blur it.

**Registration does not start anything.** `RAFIQ_LAB_ENABLED` ships off, and
with the flag down this returns before it opens a session. The flag is read at
call time rather than cached at import, so no module's import order can freeze
it — but it is an environment variable, so changing it still means restarting
the worker, exactly like every other flag here.

The same tick is available from the command line, which needs no worker:

    python -m app.labs.rafiq tick

Wrapped so a lab failure is contained: the task logs and returns rather than
raising into the beat. The lab is instrumentation, and instrumentation must
never disturb what it observes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.rafiq import config, outcomes
from app.labs.rafiq.service import RafiqLabService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: How often the forward-outcome pass runs, in minutes past the hour.
OUTCOMES_EVERY_MINUTES = 10


@celery_app.task(name="app.labs.rafiq.scheduler.rafiq_lab_tick")
def rafiq_lab_tick() -> dict[str, Any]:
    return run_async(tick())


async def tick() -> dict[str, Any]:
    """One pass. Returns what it did, so a beat log is readable."""
    if not config.enabled():
        return {"skipped": "rafiq_lab_disabled"}
    try:
        async with SessionFactory() as session:
            now = datetime.now(UTC)
            result = await RafiqLabService(session).tick(now=now)
            # The forward-outcome pass rides this task rather than taking a
            # beat entry of its own, for two reasons.
            #
            # The first is scope: `beat_schedule` lives in
            # `app/workers/celery_app.py`, outside this package, and this
            # brief forbids reaching outside it.
            #
            # The second is that a new beat entry on this deployment is not
            # reliable. Measured on dev 2026-09-12: beat's persisted schedule
            # at `/tmp/celerybeat-schedule` holds 33 entries against 48 in
            # `conf.beat_schedule`, and 17 configured tasks are never sent —
            # `security-lab-coverage` among them, which is why no security
            # evaluation has been written since 2026-08-22. An entry chained
            # inside a task that demonstrably fires cannot land in that set.
            #
            # Throttled to every tenth minute because the shortest horizon is
            # an hour: a per-minute pass would issue the same empty indexed
            # query sixty times an hour, and ten minutes still bounds how
            # late a +1h figure is recorded to under a sixth of its window.
            if now.minute % OUTCOMES_EVERY_MINUTES == 0:
                result["outcomes"] = await outcomes.record(session, now=now)
            await session.commit()
            return result
    except Exception:  # containment is the point
        logger.exception("rafiq_lab_tick_failed")
        return {"error": "rafiq_lab_tick_failed"}


@celery_app.task(name="app.labs.rafiq.scheduler.rafiq_outcomes_tick")
def rafiq_outcomes_tick() -> dict[str, Any]:
    return run_async(record_outcomes())


async def record_outcomes() -> dict[str, Any]:
    """Forward returns for candidates whose horizons have closed.

    The scheduled pass rides `tick` (see the note there). This task exists so
    the same work can be forced from the command line or a worker shell
    without waiting for a tenth minute, and takes no beat entry.

    Reads `token_market_snapshots` only — no external endpoint, so nothing
    here can be rate-limited and a metered API is never reached for.
    """
    if not config.enabled():
        return {"skipped": "rafiq_lab_disabled"}
    try:
        async with SessionFactory() as session:
            result = await outcomes.record(session, now=datetime.now(UTC))
            await session.commit()
            return result
    except Exception:  # containment is the point
        logger.exception("rafiq_outcomes_tick_failed")
        return {"error": "rafiq_outcomes_tick_failed"}

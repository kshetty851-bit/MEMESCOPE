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
from app.labs.rafiq import config
from app.labs.rafiq.service import RafiqLabService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.labs.rafiq.scheduler.rafiq_lab_tick")
def rafiq_lab_tick() -> dict[str, Any]:
    return run_async(tick())


async def tick() -> dict[str, Any]:
    """One pass. Returns what it did, so a beat log is readable."""
    if not config.enabled():
        return {"skipped": "rafiq_lab_disabled"}
    try:
        async with SessionFactory() as session:
            result = await RafiqLabService(session).tick(now=datetime.now(UTC))
            await session.commit()
            return result
    except Exception:  # containment is the point
        logger.exception("rafiq_lab_tick_failed")
        return {"error": "rafiq_lab_tick_failed"}

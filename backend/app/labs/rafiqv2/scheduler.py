"""Rafiqv2's beat task, every 30 seconds (`app/workers/celery_app.py`).

Thirty seconds, not the crontab minute: the fast rug ladder's first rungs are
at 30s and 60s, and the platform prices a young token about every 30s. A
one-minute beat would never see the 30s rung at all. It expires after one
interval, so a tick stuck behind the shared worker's minute burst is dropped
rather than run late, and an advisory lock stops two ticks overlapping.

`RAFIQV2_LAB_ENABLED` ships off: the task returns before opening a session,
so registering it starts nothing. Failures are logged and contained.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.rafiqv2 import config
from app.labs.rafiqv2.service import Rafiqv2Service
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.labs.rafiqv2.scheduler.rafiqv2_lab_tick")
def rafiqv2_lab_tick() -> dict[str, Any]:
    return run_async(tick())


async def tick() -> dict[str, Any]:
    if not config.enabled():
        return {"skipped": "rafiqv2_lab_disabled"}
    try:
        async with SessionFactory() as session:
            result = await Rafiqv2Service(session).tick(now=datetime.now(UTC))
            await session.commit()
            return result
    except Exception:  # the lab is instrumentation; it must not disturb the beat
        logger.exception("rafiqv2_lab_tick_failed")
        return {"error": "rafiqv2_lab_tick_failed"}

"""The tracker's beat tasks.

Two beat entries firing four times a day, and the cadence is the
exchange's, not ours:

* **18:30 IST** — the day's bhavcopy. NSE publishes it after the close; it is
  occasionally late, so the task re-runs hourly to 19:30 and again at 07:30
  next morning. A day that is simply not published is recorded `missing` and
  never asked about again.
* **an hourly backfill**, which walks the archive backwards a bounded number
  of days per run and stops when there is nothing pending. Resumable by
  construction, so it can be killed at any point.

IST is UTC+5:30 and the platform's Celery runs on UTC (`timezone="UTC"` in
`celery_app.py`), so 18:30 IST is 13:00 UTC. Written as UTC here rather than
switching the app's timezone, because changing that would move every other
lab's schedule.

Both are gated by `NSE_BREAKOUT_ENABLED`, read at call time. With the flag
down each returns before it opens a session or a socket.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.nse_breakout import config
from app.labs.nse_breakout.ingest import Ingest
from app.labs.nse_breakout.sources import NseArchive
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

INGEST_TASK = "app.labs.nse_breakout.scheduler.nse_tracker_ingest"
BACKFILL_TASK = "app.labs.nse_breakout.scheduler.nse_tracker_backfill"


@celery_app.task(name=INGEST_TASK)
def nse_tracker_ingest() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(ingest_tick())


@celery_app.task(name=BACKFILL_TASK)
def nse_tracker_backfill() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(backfill_tick())


async def ingest_tick() -> dict[str, Any]:
    """Today's bhavcopy, then re-derive the universe from what is stored."""
    if not config.enabled():
        return {"skipped": "nse_breakout_disabled"}
    try:
        now = datetime.now(UTC)
        async with NseArchive() as archive, SessionFactory() as session:
            job = Ingest(session, archive)
            day = await job.day(now.date(), now=now)
            universe = await job.rebuild_universe(now=now)
            gaps = await job.flag_suspect_gaps()
            await job.prune_runs()
            await session.commit()
            return {"phase": "ingest", "day": day, "universe": universe,
                    "suspect_gaps": gaps, "requests": archive.requests}
    except Exception:  # containment: never raise into the beat
        logger.exception("nse_tracker_ingest_failed")
        return {"error": "nse_tracker_ingest_failed"}


async def backfill_tick(limit: int = config.BACKFILL_DAYS_PER_RUN) -> dict[str, Any]:
    """One bounded slice of the archive walk. Does nothing once complete."""
    if not config.enabled():
        return {"skipped": "nse_breakout_disabled"}
    try:
        async with NseArchive() as archive, SessionFactory() as session:
            job = Ingest(session, archive)
            result = await job.backfill(limit=limit)
            if result["ok"]:
                result["universe"] = await job.rebuild_universe()
            await session.commit()
            return result
    except Exception:  # containment
        logger.exception("nse_tracker_backfill_failed")
        return {"error": "nse_tracker_backfill_failed"}

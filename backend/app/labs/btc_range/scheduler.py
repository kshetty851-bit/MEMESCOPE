"""The lab's one beat task: pull the latest candles every minute.

Gated by `LAB_BTC_RANGE_ENABLED` (default off). With the flag down the task
returns before it opens a session or a socket, so registering the beat entry
starts nothing.

The schedule entry is declared in `app/workers/celery_app.py`, not here: beat
does not import task modules, so a schedule that only a task module registers
never fires (the graduation lab learned that the slow way).

Containment is the point: a failed fetch must never raise into the beat. The
next minute retries from the last closed candle, so a missed run costs nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.btc_range.ingest import ingest_latest
from app.labs.btc_range.source import BinanceKlineClient, KlineError
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

TASK_NAME = "btc_range.ingest"


@celery_app.task(name=TASK_NAME)
def btc_range_ingest() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(ingest_tick())


async def ingest_tick() -> dict[str, Any]:
    """One ingest pass. Owns its session and commits explicitly."""
    if not (settings.LAB_BTC_RANGE_ENABLED or settings.LAB_BTC_MONTHLY_ENABLED):
        return {"skipped": "btc_range_disabled"}
    try:
        async with (
            BinanceKlineClient(settings.LAB_BTC_RANGE_BINANCE_URL) as client,
            SessionFactory() as session,
        ):
            result = await ingest_latest(session, client, now=datetime.now(UTC))
            await session.commit()
        return {"pages": result.pages, "fetched": result.fetched, "written": result.written}
    except KlineError as exc:
        # An unreachable or rate-limited source is expected weather, not a bug.
        logger.warning("btc_range_ingest_source_failed", error=str(exc))
        return {"error": "btc_range_source_failed"}
    except Exception:  # containment is the point: never raise into the beat
        logger.exception("btc_range_ingest_failed")
        return {"error": "btc_range_ingest_failed"}

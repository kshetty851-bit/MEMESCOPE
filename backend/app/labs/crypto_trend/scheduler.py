"""The lab's beat task and the trend engine chained behind it.

`crypto-trend-lab-tick` (registered in `app/workers/celery_app.py`, every
minute) runs the data tick, then ENQUEUES the trend engine as its own task —
the same pattern as the paper wallet's review being enqueued after the
Radar sweep. Chained rather than given a beat entry of its own because
crontab cannot offset by thirty seconds, and a second every-minute entry
would race the candles it needs. Enqueued rather than run inline so a
computation failure cannot roll back a completed fetch.

Both tasks are gated by `CRYPTO_TREND_LAB_ENABLED`, read at call time. With
the flag down the data tick returns before it opens a session or a socket,
and nothing is enqueued.

Without a worker:

    python -m app.labs.crypto_trend tick       # data, one pass
    python -m app.labs.crypto_trend trend      # engine, one pass, prints a table
    python -m app.labs.crypto_trend run        # data every 60s, foreground

Every failure is contained: a task logs and returns rather than raising into
the beat.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.crypto_trend import config
from app.labs.crypto_trend.engine import TrendEngine
from app.labs.crypto_trend.service import CryptoTrendService
from app.labs.crypto_trend.sources import MarketSource
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.labs.crypto_trend.scheduler.crypto_trend_lab_tick")
def crypto_trend_lab_tick() -> dict[str, Any]:
    result = run_async(tick())
    enqueue_trend()
    return result


@celery_app.task(name="app.labs.crypto_trend.scheduler.crypto_trend_trend_tick")
def crypto_trend_trend_tick() -> dict[str, Any]:
    return run_async(trend_tick())


def enqueue_trend() -> None:
    """Ask the worker for a trend pass, after the data tick. Swallows a broker
    failure: the worst case is a pass that does not happen, and the next
    minute's tick asks again."""
    if not config.enabled():
        return
    try:
        crypto_trend_trend_tick.delay()
    except Exception:  # pragma: no cover - broker failure path
        logger.warning("crypto_trend_trend_enqueue_failed", exc_info=True)


async def tick() -> dict[str, Any]:
    """One data pass. Returns what it did, so a beat log is readable."""
    if not config.enabled():
        return {"skipped": "crypto_trend_lab_disabled"}
    try:
        async with MarketSource() as source, SessionFactory() as session:
            result = await CryptoTrendService(session, source).tick(now=datetime.now(UTC))
            await session.commit()
            return result
    except Exception:  # containment is the point
        logger.exception("crypto_trend_lab_tick_failed")
        return {"error": "crypto_trend_lab_tick_failed"}


async def trend_tick() -> dict[str, Any]:
    """One engine pass over the universe. Reads the database only."""
    if not config.enabled():
        return {"skipped": "crypto_trend_lab_disabled"}
    try:
        async with SessionFactory() as session:
            result = await TrendEngine(session).run(now=datetime.now(UTC))
            await session.commit()
            return result
    except Exception:  # containment is the point
        logger.exception("crypto_trend_trend_tick_failed")
        return {"error": "crypto_trend_trend_tick_failed"}

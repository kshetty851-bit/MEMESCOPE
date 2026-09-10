"""The lab's beat task. Registered in `app/workers/celery_app.py` as
`crypto-trend-lab-tick`, every minute, exactly as the Rafiq lab's.

The same tick is available without a worker:

    python -m app.labs.crypto_trend tick      # one pass
    python -m app.labs.crypto_trend run       # every 60s, foreground

`CRYPTO_TREND_LAB_ENABLED` ships off, and with the flag down `tick` returns
before it opens a session or a socket. Read at call time, so no import order
can freeze it — but it is an environment variable, so changing it still means
restarting the worker.

Wrapped so a lab failure is contained: the task logs and returns rather than
raising into the beat.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.crypto_trend import config
from app.labs.crypto_trend.service import CryptoTrendService
from app.labs.crypto_trend.sources import MarketSource
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.labs.crypto_trend.scheduler.crypto_trend_lab_tick")
def crypto_trend_lab_tick() -> dict[str, Any]:
    return run_async(tick())


async def tick() -> dict[str, Any]:
    """One pass. Returns what it did, so a beat log is readable."""
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

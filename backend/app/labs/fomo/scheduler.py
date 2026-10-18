"""Two-minute forward paper-copy beat, protected by one database advisory lock."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.labs.fomo.models import FomoBook
from app.labs.fomo.service import ROSTER_REFRESH, STARTING_USD, FomoService
from app.labs.fomo.source import fetch_roster, fetch_swaps
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)
FOMO_LOCK_KEY = 0x464F4D4F


@celery_app.task(name="app.labs.fomo.scheduler.fomo_tick")
def fomo_tick() -> dict[str, Any]:
    return run_async(tick())


async def tick() -> dict[str, Any]:
    if not settings.FEATURE_FOMO_LAB_ENABLED:
        return {"skipped": "fomo_lab_disabled"}
    fomo_key = settings.FOMO_API_KEY.get_secret_value()
    helius_key = settings.HELIUS_API_KEY.get_secret_value()
    if not fomo_key or not helius_key:
        return {"skipped": "feed_key_missing"}
    now = datetime.now(UTC)
    try:
        async with SessionFactory() as session:
            locked = await session.scalar(
                select(func.pg_try_advisory_xact_lock(DRY_RUN_LOCK_NAMESPACE, FOMO_LOCK_KEY))
            )
            if not locked:
                return {"skipped": "already_running"}
            service = FomoService(session)
            book = await service.book()
            async with httpx.AsyncClient(timeout=20) as client:
                if (
                    book is None
                    or book.roster_at is None
                    or now - book.roster_at >= ROSTER_REFRESH
                ):
                    try:
                        leaders, source_captured_at = await fetch_roster(client, fomo_key)
                    except (httpx.HTTPError, ValueError) as exc:
                        if book is None:
                            return {
                                "skipped": "roster_unavailable",
                                "error": type(exc).__name__,
                            }
                        book.feed_error = f"roster_{type(exc).__name__}"
                    else:
                        roster_at = datetime.now(UTC)
                        if book is None:
                            book = FomoBook(started_at=roster_at, cash_usd=STARTING_USD)
                            session.add(book)
                            await session.flush()
                        await service.roster(book, leaders, roster_at)
                        book.source_captured_at = source_captured_at
                        book.feed_error = None
                wallets = await service.wallets_to_poll(book)
                observations, errors = await fetch_swaps(client, helius_key, wallets)
            now = datetime.now(UTC)
            await service.retry_sells(book, now)
            counts = await service.apply(book, observations, now)
            await service.mark(book, now)
            if errors:
                book.feed_error = f"swap_feed_incomplete:{len(errors)}/{len(wallets)}"
            else:
                book.feed_at = now
            await session.commit()
            return {
                "signals": counts,
                "wallets_polled": len(wallets),
                "wallets_failed": len(errors),
                "roster_at": book.roster_at.isoformat(),
            }
    except Exception:
        logger.exception("fomo_tick_failed")
        return {"failed": True}

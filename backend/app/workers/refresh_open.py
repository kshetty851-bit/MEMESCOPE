"""Dedicated Celery beat task to refresh open positions directly."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.paper.service import PaperWalletService
from app.services.market.enrichment import enqueue_priority_enrichment
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.workers.refresh_open.refresh_open_positions")
def refresh_open_positions_task() -> dict[str, Any]:
    """Force market enrichment for all currently open Paper Wallet positions."""
    return run_async(_refresh_open())


async def _refresh_open() -> dict[str, Any]:
    async with SessionFactory() as session:
        service = PaperWalletService(session)
        open_mints = await service.get_open_position_mints()

    if not open_mints:
        return {"enqueued": 0}

    await enqueue_priority_enrichment(open_mints)
    logger.info("refresh_open_positions", enqueued=len(open_mints))
    
    return {"enqueued": len(open_mints)}

"""Background tasks."""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.repositories.user import RefreshTokenRepository
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.purge_expired_refresh_tokens")
def purge_expired_refresh_tokens() -> dict[str, Any]:
    """Delete refresh tokens that expired — they can no longer be exchanged."""
    return asyncio.run(_purge_expired_refresh_tokens())


async def _purge_expired_refresh_tokens() -> dict[str, Any]:
    async with SessionFactory() as session:
        deleted = await RefreshTokenRepository(session).purge_expired()
        await session.commit()
    logger.info("refresh_tokens_purged", deleted=deleted)
    return {"deleted": deleted}


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    """Trivial task used to verify the worker and broker are wired up."""
    return "pong"

"""Background tasks."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.models.token import MetadataStatus
from app.repositories.user import RefreshTokenRepository
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.purge_expired_refresh_tokens")
def purge_expired_refresh_tokens() -> dict[str, Any]:
    """Delete refresh tokens that expired — they can no longer be exchanged."""
    return run_async(_purge_expired_refresh_tokens())


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


@celery_app.task(name="app.workers.tasks.resolve_pending_metadata")
def resolve_pending_metadata() -> dict[str, Any]:
    """Name the tokens discovery could not name at the moment it found them."""
    return run_async(_resolve_pending_metadata())


async def _resolve_pending_metadata() -> dict[str, Any]:
    """Retry the DAS lookup for tokens still sitting at PENDING.

    `TokenRepository.list_pending_metadata` and `update_metadata` have existed
    since the scanner shipped, and `SCANNER_METADATA_ATTEMPTS` has configured a
    retry cap for a loop that was never written: nothing outside the tests ever
    called either. Measured on 2026-09-13, 75,977 rows were stuck at PENDING —
    7.7% of a normal day, and 100% of everything discovered through a path that
    carries no name in its log event (PumpSwap pools, and now Meteora DBC and
    Raydium LaunchLab, which together took the nameless share to 25.6%).

    Two reasons a row is PENDING, and both end here rather than at discovery:
    the DAS indexer had not caught up yet when the scanner asked, or nobody
    asked at all because the launch event carried no name to begin with. A
    sample of 12 stuck mints resolved 12/12 on retry.

    The DAS read needs a DAS node. The production router reports
    `supports_metadata=False` — it fails over between plain JSON-RPC endpoints —
    so this asks for the vendor implementation by name and does nothing at all
    when no key is configured. Skipping loudly beats writing empty names.
    """
    from app.core.config import settings
    from app.repositories.token import TokenRepository
    from app.services.rpc.registry import get_rpc
    from app.services.scanner.parser import parse_asset_metadata

    if not settings.helius_configured:
        logger.warning("metadata_backfill_skipped", reason="no DAS provider configured")
        return {"skipped": "no DAS provider"}

    rpc = get_rpc("helius")
    await rpc.start()
    resolved = exhausted = retried = 0
    try:
        async with SessionFactory() as session:
            repository = TokenRepository(session)
            tokens = await repository.list_pending_metadata(
                limit=settings.METADATA_BACKFILL_BATCH,
                max_attempts=settings.SCANNER_METADATA_ATTEMPTS,
            )
            for token in tokens:
                try:
                    asset = await rpc.get_asset(token.mint_address, attempts=1)
                except Exception:
                    # One unreadable mint costs that mint, not the batch. The
                    # row keeps its attempt count and comes back next tick.
                    logger.warning(
                        "metadata_backfill_failed", mint=token.mint_address, exc_info=True
                    )
                    continue

                metadata = parse_asset_metadata(asset) if asset else None
                named = bool(metadata and (metadata.name or metadata.symbol))
                # One attempt short of the cap is the last one this row gets, so
                # retire it now rather than leaving it to be re-read for ever.
                last_try = token.metadata_attempts + 1 >= settings.SCANNER_METADATA_ATTEMPTS
                status = (
                    MetadataStatus.RESOLVED
                    if named
                    else (MetadataStatus.FAILED if last_try else MetadataStatus.PENDING)
                )
                await repository.update_metadata(
                    token,
                    name=metadata.name if metadata else None,
                    symbol=metadata.symbol if metadata else None,
                    metadata_uri=metadata.metadata_uri if metadata else None,
                    image_url=metadata.image_url if metadata else None,
                    decimals=metadata.decimals if metadata else None,
                    status=status,
                )
                resolved += named
                exhausted += (not named) and last_try
                retried += (not named) and not last_try
            await session.commit()
    finally:
        await rpc.close()

    logger.info(
        "metadata_backfill_ran", resolved=resolved, exhausted=exhausted, retried=retried
    )
    return {"resolved": resolved, "exhausted": exhausted, "retried": retried}

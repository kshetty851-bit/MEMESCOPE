import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.celery_app import shared_task
from app.core.utils.async_celery import run_async
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)

async def _prune_old_snapshots(dry_run: bool):
    """Prunes token_market_snapshots safely, respecting the Paper Wallet watermark."""
    async with async_session_factory() as session:
        # First check the paper wallet watermark
        watermark_query = text(
            "SELECT COALESCE(MIN(last_evaluated_at), NOW()) FROM paper_positions WHERE status = 'open'"
        )
        watermark = (await session.execute(watermark_query)).scalar()
        
        # We only prune data older than 14 days AND older than the oldest open paper wallet position.
        cutoff_date = datetime.utcnow() - timedelta(days=14)
        safe_cutoff = min(cutoff_date, watermark.replace(tzinfo=None) if watermark.tzinfo else watermark)
        
        if dry_run:
            logger.info(f"[DRY RUN] Would prune snapshots older than {safe_cutoff}")
            count_query = text("SELECT COUNT(*) FROM token_market_snapshots WHERE captured_at < :cutoff")
            eligible = (await session.execute(count_query, {"cutoff": cutoff_date})).scalar()
            would_prune = (await session.execute(count_query, {"cutoff": safe_cutoff})).scalar()
            protected = eligible - would_prune
            
            logger.info(f"[DRY RUN] Eligible by age (>14d): {eligible}")
            logger.info(f"[DRY RUN] Protected by paper wallet watermark: {protected}")
            logger.info(f"[DRY RUN] Removable: {would_prune}")
            logger.info(f"[DRY RUN] Estimated disk reclaimed: {would_prune * 2} KB")
            return
        else:
            logger.info(f"Pruning snapshots older than {safe_cutoff}")
            prune_query = text(
                "DELETE FROM token_market_snapshots WHERE captured_at < :cutoff"
            )
            result = await session.execute(prune_query, {"cutoff": safe_cutoff})
            await session.commit()
            deleted_count = result.rowcount
            logger.info(f"Deleted {deleted_count} old snapshots")

@shared_task(name="retention.prune_snapshots")
def prune_snapshots(dry_run: bool = True):
    """Celery task to prune old snapshots."""
    run_async(_prune_old_snapshots(dry_run))

import argparse
import asyncio
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import text
from app.db.session import async_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def batched_prune(chunk_hours: int, pause_sec: float):
    logger.info("Initializing batched prune...")
    
    async with async_session_factory() as session:
        watermark_query = text("SELECT COALESCE(MIN(last_evaluated_at), NOW()) FROM paper_positions WHERE status = 'open'")
        watermark = (await session.execute(watermark_query)).scalar()
        
        cutoff_date = datetime.utcnow() - timedelta(days=14)
        safe_cutoff = min(cutoff_date, watermark.replace(tzinfo=None) if watermark.tzinfo else watermark)
        
        # Get oldest snapshot
        min_date_query = text("SELECT MIN(captured_at) FROM token_market_snapshots WHERE captured_at < :cutoff")
        oldest_date = (await session.execute(min_date_query, {"cutoff": safe_cutoff})).scalar()
        
        if not oldest_date:
            logger.info("No eligible snapshots to prune.")
            return

        current_start = oldest_date
        total_deleted = 0
        batch_count = 0
        current_chunk_hours = 3 # Start conservatively
        
        while current_start < safe_cutoff:
            current_end = min(current_start + timedelta(hours=current_chunk_hours), safe_cutoff)
            
            logger.info(f"Batch {batch_count+1}: Pruning {current_start} -> {current_end}")
            start_t = time.time()
            
            delete_query = text("""
                DELETE FROM token_market_snapshots 
                WHERE captured_at >= :start AND captured_at < :end
            """)
            
            result = await session.execute(delete_query, {"start": current_start, "end": current_end})
            await session.commit()
            
            deleted = result.rowcount
            total_deleted += deleted
            duration = (time.time() - start_t) * 1000
            
            logger.info(f"Deleted {deleted} rows in {duration:.0f}ms.")
            
            current_start = current_end
            batch_count += 1
            
            # Gradually increase batch size after first 3 successful batches
            if batch_count >= 3 and current_chunk_hours < chunk_hours:
                current_chunk_hours = min(current_chunk_hours * 2, chunk_hours)
                logger.info(f"Expanding batch size to {current_chunk_hours} hours")
            
            if pause_sec > 0:
                logger.info(f"Pausing for {pause_sec}s...")
                await asyncio.sleep(pause_sec)
                
        logger.info(f"Prune Complete. Total deleted: {total_deleted} in {batch_count} batches.")
        
        logger.info("Running safe maintenance (ANALYZE and VACUUM)...")
        # Connection for vacuum must be out of transaction block usually, 
        # but SQLAlchemy text can handle it if we set autocommit or isolation_level
        # Alternatively, we just log it and do it via a different connection.
        await session.execute(text("COMMIT"))
        await session.execute(text("VACUUM ANALYZE token_market_snapshots"))
        logger.info("Maintenance complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-hours", type=int, default=6) # Max expansion to 6-hour window
    parser.add_argument("--pause-sec", type=float, default=5.0)
    args = parser.parse_args()
    
    asyncio.run(batched_prune(args.chunk_hours, args.pause_sec))

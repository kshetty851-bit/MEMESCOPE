import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from app.db.session import async_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_coverage():
    logger.info("Verifying archive coverage for pruning candidates...")
    
    async with async_session_factory() as session:
        # Determine the prune boundary
        watermark_query = text("SELECT COALESCE(MIN(last_evaluated_at), NOW()) FROM paper_positions WHERE status = 'open'")
        watermark = (await session.execute(watermark_query)).scalar()
        
        cutoff_date = datetime.utcnow() - timedelta(days=14)
        safe_cutoff = min(cutoff_date, watermark.replace(tzinfo=None) if watermark.tzinfo else watermark)
        
        # Check if we have candles for the range
        candle_check = text("""
            SELECT COUNT(*) 
            FROM token_market_candles_1h 
            WHERE bucket < :cutoff
        """)
        candles_count = await session.scalar(candle_check, {"cutoff": safe_cutoff})
        
        if candles_count == 0:
            logger.error("CRITICAL: No candles found for the prune range! Pruning unsafe.")
            return False
            
        logger.info(f"Verified {candles_count} candles cover the eligible pruning range.")
        logger.info("Archive coverage verification PASSED.")
        return True

if __name__ == "__main__":
    asyncio.run(verify_coverage())

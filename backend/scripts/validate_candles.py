import argparse
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from app.db.session import async_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def validate_equivalence():
    query = text("""
        WITH sample AS (
            SELECT mint_address, date_trunc('hour', captured_at) AS bucket
            FROM token_market_candles_1h
            LIMIT 5
        ),
        raw_agg AS (
            SELECT 
                s.mint_address,
                s.bucket,
                MIN(r.price_usd) as expected_low,
                MAX(r.price_usd) as expected_high,
                COUNT(*) as obs_count,
                (SELECT price_usd FROM token_market_snapshots 
                 WHERE mint_address = s.mint_address AND date_trunc('hour', captured_at) = s.bucket
                 ORDER BY captured_at ASC LIMIT 1) as expected_open,
                (SELECT price_usd FROM token_market_snapshots 
                 WHERE mint_address = s.mint_address AND date_trunc('hour', captured_at) = s.bucket
                 ORDER BY captured_at DESC LIMIT 1) as expected_close,
                (SELECT market_cap FROM token_market_snapshots 
                 WHERE mint_address = s.mint_address AND date_trunc('hour', captured_at) = s.bucket
                 ORDER BY captured_at DESC LIMIT 1) as expected_market_cap
            FROM sample s
            JOIN token_market_snapshots r 
              ON r.mint_address = s.mint_address AND date_trunc('hour', r.captured_at) = s.bucket
            GROUP BY s.mint_address, s.bucket
        )
        SELECT 
            c.mint_address, c.bucket, 
            c.open_price, c.high_price, c.low_price, c.close_price, c.close_market_cap,
            ra.expected_open, ra.expected_high, ra.expected_low, ra.expected_close, ra.expected_market_cap,
            ra.obs_count
        FROM token_market_candles_1h c
        JOIN raw_agg ra ON c.mint_address = ra.mint_address AND c.bucket = ra.bucket
    """)
    
    async with async_session_factory() as session:
        result = await session.execute(query)
        rows = result.all()
        if not rows:
            logger.warning("No candles found to validate. Run backfill first.")
            return

        for r in rows:
            assert r.open_price == r.expected_open, f"Open price mismatch for {r.mint_address} at {r.bucket}"
            assert r.high_price == r.expected_high, f"High price mismatch for {r.mint_address} at {r.bucket}"
            assert r.low_price == r.expected_low, f"Low price mismatch for {r.mint_address} at {r.bucket}"
            assert r.close_price == r.expected_close, f"Close price mismatch for {r.mint_address} at {r.bucket}"
            assert r.close_market_cap == r.expected_market_cap, f"Market cap mismatch for {r.mint_address} at {r.bucket}"
            logger.info(f"OK: {r.mint_address} @ {r.bucket} (from {r.obs_count} snapshots)")

if __name__ == "__main__":
    asyncio.run(validate_equivalence())

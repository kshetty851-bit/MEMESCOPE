import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from app.db.session import async_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill_chunk(start_time: datetime, end_time: datetime, dry_run: bool) -> int:
    query = text("""
        WITH buckets AS (
            SELECT
                mint_address,
                date_trunc('hour', captured_at) AS bucket,
                price_usd,
                market_cap,
                liquidity_usd,
                volume_1h,
                ROW_NUMBER() OVER (PARTITION BY mint_address, date_trunc('hour', captured_at) ORDER BY captured_at ASC) as rn_asc,
                ROW_NUMBER() OVER (PARTITION BY mint_address, date_trunc('hour', captured_at) ORDER BY captured_at DESC) as rn_desc
            FROM token_market_snapshots
            WHERE captured_at >= :start_time AND captured_at < :end_time
        ),
        agg AS (
            SELECT
                mint_address,
                bucket,
                MIN(price_usd) AS low_price,
                MAX(price_usd) AS high_price
            FROM buckets
            GROUP BY mint_address, bucket
        ),
        candles AS (
            SELECT
                agg.mint_address,
                agg.bucket,
                first_row.price_usd AS open_price,
                agg.high_price,
                agg.low_price,
                last_row.price_usd AS close_price,
                last_row.market_cap AS close_market_cap,
                last_row.liquidity_usd AS close_liquidity_usd,
                last_row.volume_1h AS volume
            FROM agg
            JOIN buckets first_row ON agg.mint_address = first_row.mint_address AND agg.bucket = first_row.bucket AND first_row.rn_asc = 1
            JOIN buckets last_row ON agg.mint_address = last_row.mint_address AND agg.bucket = last_row.bucket AND last_row.rn_desc = 1
        )
        INSERT INTO token_market_candles_1h (
            mint_address, bucket, open_price, high_price, low_price, close_price, 
            close_market_cap, close_liquidity_usd, volume
        )
        SELECT * FROM candles
        ON CONFLICT (mint_address, bucket) DO UPDATE SET
            open_price = EXCLUDED.open_price,
            high_price = EXCLUDED.high_price,
            low_price = EXCLUDED.low_price,
            close_price = EXCLUDED.close_price,
            close_market_cap = EXCLUDED.close_market_cap,
            close_liquidity_usd = EXCLUDED.close_liquidity_usd,
            volume = EXCLUDED.volume;
    """)
    
    async with async_session_factory() as session:
        if dry_run:
            logger.info(f"[DRY RUN] Would backfill from {start_time} to {end_time}")
            return 0
        else:
            result = await session.execute(query, {"start_time": start_time, "end_time": end_time})
            await session.commit()
            return result.rowcount

async def main():
    parser = argparse.ArgumentParser(description="Backfill 1h candles from snapshots")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to the DB")
    parser.add_argument("--days", type=int, default=30, help="Number of days to backfill")
    parser.add_argument("--chunk-size-hours", type=int, default=24, help="Chunk size in hours")
    args = parser.parse_args()

    end_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(days=args.days)
    
    logger.info(f"Starting backfill from {start_time} to {end_time} (Dry run: {args.dry_run})")
    
    current = start_time
    total_candles = 0
    while current < end_time:
        next_chunk = min(current + timedelta(hours=args.chunk_size_hours), end_time)
        try:
            inserted = await backfill_chunk(current, next_chunk, args.dry_run)
            total_candles += inserted
            logger.info(f"Processed chunk {current} -> {next_chunk}: UPSERTED {inserted} candles.")
        except Exception as e:
            logger.error(f"Error processing chunk {current} -> {next_chunk}: {e}")
            break
        current = next_chunk

    logger.info(f"Backfill complete. Total candles updated: {total_candles}")

if __name__ == "__main__":
    asyncio.run(main())

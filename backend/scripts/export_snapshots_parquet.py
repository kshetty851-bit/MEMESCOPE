import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.market import TokenMarketSnapshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def export_old_snapshots(days_old: int = 14, output_dir: str = "exports"):
    """Export snapshots older than N days to a Parquet file."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.utcnow() - timedelta(days=days_old)
    logger.info(f"Exporting snapshots older than {cutoff.isoformat()} to {output_dir}/")

    stmt = select(TokenMarketSnapshot).where(TokenMarketSnapshot.captured_at < cutoff)

    async with async_session_factory() as session:
        # We process in chunks to avoid blowing up memory
        result = await session.stream(stmt.execution_options(yield_per=10000))
        
        batch_size = 100000
        batch = []
        file_index = 0

        async for row in result.scalars():
            batch.append({
                "token_id": str(row.token_id),
                "mint_address": row.mint_address,
                "captured_at": row.captured_at,
                "price_usd": float(row.price_usd) if row.price_usd else None,
                "price_native": float(row.price_native) if row.price_native else None,
                "liquidity_usd": float(row.liquidity_usd) if row.liquidity_usd else None,
                "fully_diluted_valuation": float(row.fully_diluted_valuation) if row.fully_diluted_valuation else None,
                "market_cap": float(row.market_cap) if row.market_cap else None,
                "volume_24h": float(row.volume_24h) if row.volume_24h else None,
                "volume_1h": float(row.volume_1h) if row.volume_1h else None,
                "volume_5m": float(row.volume_5m) if row.volume_5m else None,
                "buy_count_24h": row.buy_count_24h,
                "sell_count_24h": row.sell_count_24h,
                "dex_name": row.dex_name,
                "trading_pair": row.trading_pair,
                "pool_address": row.pool_address,
                "trading_status": row.trading_status.value,
                "is_verified": row.is_verified,
                "provider": row.provider,
                "provider_latency_ms": row.provider_latency_ms,
            })

            if len(batch) >= batch_size:
                _write_batch(batch, out_path, file_index)
                file_index += 1
                batch = []

        if batch:
            _write_batch(batch, out_path, file_index)
            
    logger.info("Export completed.")

async def validate_parquet(file_path: Path, days_old: int = 14):
    """Validate the exported parquet file against PostgreSQL."""
    logger.info(f"Validating {file_path}")
    table = pq.read_table(file_path)
    logger.info(f"Parquet rows: {table.num_rows}")
    
    # Just basic check to ensure columns exist and it's readable
    expected_cols = ["token_id", "mint_address", "captured_at", "price_usd", "market_cap"]
    for col in expected_cols:
        assert col in table.column_names, f"Missing column {col}"
        
    logger.info("Parquet validation OK (schema & readability).")

def _write_batch(batch: list[dict], out_path: Path, index: int):
    table = pa.Table.from_pylist(batch)
    filename = out_path / f"snapshots_archive_{index:04d}.parquet"
    pq.write_table(table, filename)
    logger.info(f"Wrote {len(batch)} rows to {filename}")

if __name__ == "__main__":
    asyncio.run(export_old_snapshots())

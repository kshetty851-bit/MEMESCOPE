import asyncio
from decimal import Decimal
from sqlalchemy import text
from app.db.session import SessionFactory

async def backfill():
    async with SessionFactory() as session:
        # Check how many positions are missing entry_market_cap
        missing_res = await session.execute(
            text("SELECT count(*) FROM paper_positions WHERE entry_market_cap IS NULL AND status = 'open'")
        )
        missing_open = missing_res.scalar()
        print(f"Missing open positions entry_market_cap: {missing_open}")
        
        # Backfill entry_market_cap using the captured_at timestamp of the closest snapshot
        # For each position missing entry_market_cap, we find the snapshot
        # exactly matching the entry price or closest to opened_at
        
        query = text("""
            UPDATE paper_positions p
            SET entry_market_cap = (
                SELECT s.market_cap
                FROM token_market_snapshots s
                WHERE s.mint_address = p.mint_address
                ORDER BY abs(extract(epoch from (s.captured_at - p.opened_at))) ASC
                LIMIT 1
            )
            WHERE p.entry_market_cap IS NULL
        """)
        
        res = await session.execute(query)
        await session.commit()
        print(f"Updated {res.rowcount} rows with entry_market_cap")

if __name__ == "__main__":
    asyncio.run(backfill())

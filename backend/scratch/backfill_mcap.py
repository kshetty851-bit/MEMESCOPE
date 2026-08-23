import asyncio
from sqlalchemy import text
import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import engine

async def main():
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT COUNT(*), COUNT(entry_market_cap) FROM paper_positions"))
        total, with_mcap = res.fetchone()
        print(f"Total positions: {total}, with entry_market_cap: {with_mcap}")
        
        # Check backfill
        update_query = text("""
            WITH entry_snapshot AS (
                SELECT p.id, s.market_cap
                FROM paper_positions p
                JOIN token_market_snapshots s 
                  ON s.mint_address = p.mint_address
                 AND s.captured_at = p.opened_at
                WHERE p.entry_market_cap IS NULL
            )
            UPDATE paper_positions
            SET entry_market_cap = entry_snapshot.market_cap
            FROM entry_snapshot
            WHERE paper_positions.id = entry_snapshot.id
            RETURNING paper_positions.id, paper_positions.entry_market_cap
        """)
        updated = await conn.execute(update_query)
        rows = updated.fetchall()
        print(f"Backfilled {len(rows)} positions")

asyncio.run(main())

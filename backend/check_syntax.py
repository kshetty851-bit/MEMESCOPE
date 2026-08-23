import asyncio
from datetime import datetime
from sqlalchemy import text
from app.core.database import get_engine

async def main():
    async for session in get_engine():
        stmt = text("""
            SELECT m.mint, latest.price_usd
            FROM unnest(:mints::varchar[]) AS m(mint)
            CROSS JOIN LATERAL (
                SELECT price_usd
                FROM token_market_snapshots
                WHERE mint_address = m.mint
                  AND captured_at <= :as_of
                ORDER BY captured_at DESC
                LIMIT 1
            ) latest
        """).bindparams(mints=["mint1", "mint2"], as_of=datetime.now())
        
        try:
            # We don't execute, just check if it compiles.
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            print("Compiled OK")
        except Exception as e:
            print("Error compiling:", e)
        break

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from datetime import datetime
from sqlalchemy import text
from app.core.database import get_engine
from app.core.config import settings

async def main():
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            mints = ["mint1", "mint2"]
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
            """).bindparams(mints=mints, as_of=datetime.now())
            
            # Use dictionary execution to avoid SQLAlchemy array typing issues
            await conn.execute(stmt)
            print("DB Syntax OK")
    except Exception as e:
        print("Error executing:", type(e), e)
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())

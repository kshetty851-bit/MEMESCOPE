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
        res = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'token_market_snapshots'
        """))
        for row in res.fetchall():
            print(row[0])

asyncio.run(main())

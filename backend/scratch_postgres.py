import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    try:
        engine = create_async_engine("postgresql+asyncpg://memescope:ea41b50f36c99bae15d4ce6a60106d1e0b49740cb628dcb6d1b78af52665a063@localhost:5432/memescope")
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT COUNT(*) FROM paper_positions WHERE status = 'open'"))
            print(f"Open positions: {res.scalar()}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())

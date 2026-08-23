import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.market import TokenMarketSnapshot

async def main():
    async with SessionFactory() as session:
        rows = await session.execute(
            select(TokenMarketSnapshot.mint_address)
            .where(TokenMarketSnapshot.captured_at.is_(None))
        )
        for row in rows:
            print(row.mint_address)

if __name__ == "__main__":
    asyncio.run(main())

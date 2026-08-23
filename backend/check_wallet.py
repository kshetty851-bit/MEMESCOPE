import asyncio
from app.db.base import async_session_maker
from sqlalchemy import select
from app.models.paper import PaperWallet

async def main():
    async with async_session_maker() as session:
        wallet = (await session.execute(select(PaperWallet).where(PaperWallet.archived_at.is_(None)))).scalars().first()
        print(f"Live wallet strategy ID: {wallet.strategy_id}")

if __name__ == "__main__":
    asyncio.run(main())

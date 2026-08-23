import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperWallet

async def main():
    async with SessionFactory() as session:
        rows = await session.scalars(select(PaperWallet))
        for w in rows:
            print(w.id, w.generation, w.archived_at)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperPosition

async def main():
    async with SessionFactory() as session:
        rows = await session.execute(
            select(PaperPosition.mint_address, PaperPosition.status, PaperPosition.opened_at)
            .where(PaperPosition.status == 'open')
        )
        for row in rows:
            print(row.mint_address, row.status, row.opened_at)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperWallet

async def main():
    async with SessionFactory() as session:
        res = await session.execute(
            select(PaperWallet)
            .where(PaperWallet.strategy_id == 'paper_track_record_tp125_sl50_v1')
        )
        for w in res.scalars():
            print(f"Track Record Wallet ID: {w.id}, Gen: {w.generation}, Archived: {w.archived_at}")

asyncio.run(main())

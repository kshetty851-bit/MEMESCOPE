import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperPosition, PaperWallet

async def main():
    async with SessionFactory() as session:
        rows = await session.execute(
            select(PaperPosition.mint_address, PaperPosition.wallet_id, PaperWallet.generation)
            .join(PaperWallet, PaperWallet.id == PaperPosition.wallet_id)
            .where(PaperPosition.status == 'open')
        )
        gen1 = []
        gen2 = []
        for row in rows:
            if row.generation == 1:
                gen1.append(row.mint_address)
            elif row.generation == 2:
                gen2.append(row.mint_address)
        print(f"Gen1 Open: {len(gen1)}")
        print(f"Gen2 Open: {len(gen2)}")

if __name__ == "__main__":
    asyncio.run(main())

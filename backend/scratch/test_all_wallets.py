import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperWallet
from app.paper.service import PaperWalletService

async def main():
    async with SessionFactory() as session:
        service = PaperWalletService(session)
        wallets = await session.scalars(select(PaperWallet))
        for w in wallets:
            print(f"Wallet: {w.id} (Gen {w.generation})")
            # Get positions using the service
            positions = await service._repository.all_positions(w.id)
            open_pos = [p for p in positions if p.status == "open"]
            mints = [p.mint_address for p in open_pos]
            if not mints:
                continue
            
            prices = await service._market.latest_for_mints(mints)
            for p in open_pos:
                market = prices.get(p.mint_address)
                if not market or not market.captured_at:
                    print(f"  Missing current_price_at: {p.mint_address}")
            print(f"  Total open: {len(open_pos)}")

if __name__ == "__main__":
    asyncio.run(main())

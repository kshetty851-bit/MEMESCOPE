import asyncio
from sqlalchemy import select, func
from app.db.session import SessionFactory
from app.models.paper import PaperPosition, PaperWallet

async def main():
    async with SessionFactory() as session:
        wallet = await session.scalar(select(PaperWallet).where(PaperWallet.generation == 2))
        if not wallet:
            print("No Gen 2 wallet")
            return
            
        count = await session.scalar(
            select(func.count(PaperPosition.id))
            .where(PaperPosition.wallet_id == wallet.id, PaperPosition.status == "open")
        )
        print(f"Total open in DB for Gen 2: {count}")
        
        # also print all of them and their current_price_at
        from app.paper.service import PaperWalletService
        service = PaperWalletService(session)
        positions = await service._repository.all_positions(wallet.id)
        open_pos = [p for p in positions if p.status == "open"]
        mints = [p.mint_address for p in open_pos]
        prices = await service._market.latest_for_mints(mints)
        
        missing = 0
        for p in open_pos:
            market = prices.get(p.mint_address)
            if not market or not market.captured_at:
                missing += 1
                print(f"MISSING: {p.mint_address}")
        print(f"Total missing: {missing}")

if __name__ == "__main__":
    asyncio.run(main())

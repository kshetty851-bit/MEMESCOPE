import asyncio
from datetime import datetime, timezone
from app.db.session import SessionFactory
from app.paper.service import PaperWalletService

async def main():
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        service = PaperWalletService(session)
        wallet = await service.wallet(now=now)
        positions = await service._repository.all_positions(wallet.id)
        open_pos = [p for p in positions if p.status == 'open']
        mints = [p.mint_address for p in open_pos]
        prices = await service._market.latest_for_mints(mints, since=wallet.resume_watermark_at)
        
        count = 0
        for p in open_pos:
            market = prices.get(p.mint_address)
            if not market:
                print(f"NO MARKET: {p.mint_address}")
                count += 1
            elif market.price_usd is None:
                print(f"NULL PRICE: {p.mint_address}")
                count += 1
        print(f"Total: {count}")

if __name__ == "__main__":
    asyncio.run(main())

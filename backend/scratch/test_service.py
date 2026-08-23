import asyncio
from datetime import datetime, timezone
from app.db.session import SessionFactory
from app.paper.service import PaperWalletService

async def main():
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        service = PaperWalletService(session)
        wallet_read = await service.read(now=now)
        positions = wallet_read.positions
        print(f"Total positions: {len(positions)}")
        for pos in positions:
            if pos.status == 'open':
                mint = pos.mint_address
                price = wallet_read.prices.get(mint)
                price_time = wallet_read.price_times.get(mint)
                print(f"Mint: {mint}, Price: {price}, Time: {price_time}")

if __name__ == "__main__":
    asyncio.run(main())

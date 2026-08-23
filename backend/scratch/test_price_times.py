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
        for p in positions:
            if p.status == 'open':
                observed_at = wallet_read.price_times.get(p.mint_address)
                print(f"Mint: {p.mint_address}, observed_at: {observed_at}")

if __name__ == "__main__":
    asyncio.run(main())

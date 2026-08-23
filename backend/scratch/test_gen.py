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
        wallets = set(p.wallet_id for p in positions)
        print(f"Wallets: {wallets}")

if __name__ == "__main__":
    asyncio.run(main())

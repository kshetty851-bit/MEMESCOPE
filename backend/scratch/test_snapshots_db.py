import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, func, text
from app.db.session import SessionFactory
from app.models.paper import PaperWallet
from app.models.market import TokenMarketSnapshot
from app.paper.service import PaperWalletService

async def main():
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        service = PaperWalletService(session)
        wallet = await service.wallet(now=now)
        print(f"Wallet Gen {wallet.generation} watermark: {wallet.resume_watermark_at}")
        
        positions = await service._repository.all_positions(wallet.id)
        open_mints = [p.mint_address for p in positions if p.status == 'open']
        print(f"Total open: {len(open_mints)}")
        
        for mint in open_mints:
            max_captured = await session.scalar(
                select(func.max(TokenMarketSnapshot.captured_at))
                .where(TokenMarketSnapshot.mint_address == mint)
            )
            max_captured_since = await session.scalar(
                select(func.max(TokenMarketSnapshot.captured_at))
                .where(TokenMarketSnapshot.mint_address == mint)
                .where(TokenMarketSnapshot.captured_at >= wallet.resume_watermark_at)
            )
            print(f"Mint: {mint}, Max captured since watermark: {max_captured_since}")

if __name__ == "__main__":
    asyncio.run(main())

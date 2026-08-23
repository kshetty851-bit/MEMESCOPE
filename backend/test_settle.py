import asyncio
from datetime import datetime, timezone
from app.db.session import SessionFactory
from app.paper.repository import PaperRepository
from app.paper.service import PaperWalletService
from app.repositories.market import MarketSnapshotRepository

async def main():
    async with SessionFactory() as session:
        repo = PaperRepository(session)
        wallet = await repo.live_wallet()
        pos = await repo.position_for(wallet.id, '8T3suJtKUGrWRytVNKe7RLV81AumvmBPQfEkyeHtpump')
        print(f"Position status: {pos.status}, last_evaluated_at: {pos.last_evaluated_at}")
        
        market_repo = MarketSnapshotRepository(session)
        service = PaperWalletService(repo, market_repo, session)
        
        await service._settle_exits(wallet, [pos])
        await session.commit()
        
        pos = await repo.position_for(wallet.id, '8T3suJtKUGrWRytVNKe7RLV81AumvmBPQfEkyeHtpump')
        print(f"Position status: {pos.status}, last_evaluated_at: {pos.last_evaluated_at}")

if __name__ == "__main__":
    asyncio.run(main())

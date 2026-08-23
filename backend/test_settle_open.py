import asyncio
from datetime import datetime, timezone, timedelta
from app.db.session import SessionFactory
from sqlalchemy import select
from app.paper.repository import PaperRepository
from app.paper.service import PaperWalletService
from app.repositories.market import MarketSnapshotRepository
from app.models.paper import PaperPosition

async def main():
    async with SessionFactory() as session:
        repo = PaperRepository(session)
        wallet = await repo.live_wallet()
        
        # Get an OPEN position that is stuck
        stmt = select(PaperPosition).where(
            PaperPosition.wallet_id == wallet.id,
            PaperPosition.status == 'open',
            PaperPosition.last_evaluated_at < datetime.now(timezone.utc) - timedelta(hours=1)
        ).limit(1)
        pos = (await session.execute(stmt)).scalars().first()
        
        if not pos:
            print("No open stuck position found!")
            return
            
        print(f"Testing position: {pos.mint_address}")
        print(f"Status: {pos.status}, last_evaluated_at: {pos.last_evaluated_at}")
        
        market_repo = MarketSnapshotRepository(session)
        service = PaperWalletService(repo, market_repo)
        
        await service._settle_exits(wallet, [pos])
        await session.commit()
        
        await session.refresh(pos)
        print(f"After _settle_exits -> Status: {pos.status}, last_evaluated_at: {pos.last_evaluated_at}")

if __name__ == "__main__":
    asyncio.run(main())

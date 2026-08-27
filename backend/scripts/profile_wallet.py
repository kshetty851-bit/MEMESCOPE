import asyncio
import time
from backend.app.core.database import SessionLocal
from backend.app.paper.service import PaperWalletService
from backend.app.paper.service import utcnow

async def main():
    async with SessionLocal() as session:
        service = PaperWalletService(session)
        now = utcnow()
        
        t0 = time.time()
        wallet = await service.wallet(now=now)
        print(f"wallet: {time.time() - t0:.3f}s")
        
        t0 = time.time()
        positions = await service._repository.all_positions(wallet.id)
        print(f"positions: {time.time() - t0:.3f}s, len={len(positions)}")
        
        open_rows = [row for row in positions if row.status == 'OPEN']
        mints = [row.mint_address for row in open_rows]
        
        t0 = time.time()
        await service._market.latest_for_mints(mints, since=wallet.resume_watermark_at)
        print(f"latest_for_mints: {time.time() - t0:.3f}s")
        
        t0 = time.time()
        universe = await service._radar.entries_present_since(wallet.started_at)
        print(f"entries_present_since: {time.time() - t0:.3f}s, len={len(universe)}")
        
        u_mints = [row.mint_address for row in universe]
        
        t0 = time.time()
        await service._market.price_as_of_for_mints(u_mints, as_of=wallet.started_at)
        print(f"price_as_of_for_mints: {time.time() - t0:.3f}s")
        
        t0 = time.time()
        await service._market.latest_for_mints(u_mints)
        print(f"latest_for_mints (universe): {time.time() - t0:.3f}s")
        
        t0 = time.time()
        await service._waiting_for(wallet, cash=100)
        print(f"waiting_for: {time.time() - t0:.3f}s")
        
        t0 = time.time()
        await service.read(now=now)
        print(f"full read: {time.time() - t0:.3f}s")

if __name__ == "__main__":
    asyncio.run(main())

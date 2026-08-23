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
        
        print(f"Resume watermark: {wallet.resume_watermark_at}")
        snapshots = await service._market.latest_for_mints(mints, since=wallet.resume_watermark_at)
        
        missing = []
        for p in open_pos:
            if p.mint_address not in snapshots:
                missing.append(p.mint_address)
                
        print(f"Total open: {len(open_pos)}")
        print(f"Total missing with 'since': {len(missing)}")
        for m in missing:
            print(f"MISSING: {m}")

if __name__ == "__main__":
    asyncio.run(main())

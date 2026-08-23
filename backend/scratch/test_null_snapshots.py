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
        open_rows = [row for row in positions if row.status == 'open']
        snapshots = await service._market.latest_for_mints(
            [row.mint_address for row in open_rows], since=wallet.resume_watermark_at
        )
        print(f"Total open Gen2: {len(open_rows)}")
        for r in open_rows:
            if r.mint_address not in snapshots:
                print(f"MISSING SNAPSHOT: {r.mint_address}")
            elif snapshots[r.mint_address].captured_at is None:
                print(f"NULL CAPTURED_AT: {r.mint_address}")

if __name__ == "__main__":
    asyncio.run(main())

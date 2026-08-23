import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperWallet
from app.paper.service import PaperWalletService
from app.paper.api import _to_position

async def main():
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        wallets = await session.scalars(select(PaperWallet))
        for w in wallets:
            service = PaperWalletService(session)
            # Mock the live_wallet to return this specific wallet
            service.wallet = lambda now=now: w
            
            # Read the wallet state
            try:
                # Need to manually construct read since we are bypassing self.wallet()
                positions = await service._repository.all_positions(w.id)
                open_rows = [row for row in positions if row.status == "open"]
                
                snapshots = await service._market.latest_for_mints(
                    [row.mint_address for row in open_rows], since=w.resume_watermark_at
                )
                prices = {
                    row.mint_address: snapshots[row.mint_address].price_usd if row.mint_address in snapshots else None
                    for row in open_rows
                }
                price_times = {
                    row.mint_address: snapshots[row.mint_address].captured_at if row.mint_address in snapshots else None
                    for row in open_rows
                }
                
                missing = 0
                for r in open_rows:
                    if price_times[r.mint_address] is None:
                        print(f"Gen {w.generation}: Missing current_price_at for {r.mint_address}")
                        missing += 1
                if missing:
                    print(f"Gen {w.generation}: Total missing = {missing}")
            except Exception as e:
                print(f"Gen {w.generation} Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

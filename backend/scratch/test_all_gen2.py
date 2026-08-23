import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperWallet, PaperPosition
from app.paper.service import PaperWalletService
from app.paper.api import _to_position
from datetime import datetime, timezone

async def main():
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        wallets = await session.scalars(select(PaperWallet).where(PaperWallet.generation == 2))
        wallets = list(wallets)
        print(f"Found {len(wallets)} Gen 2 wallets.")
        
        for w in wallets:
            service = PaperWalletService(session)
            service.wallet = lambda now=now, w=w: w
            read = await service.read(now=now)
            
            open_rows = [row for row in read.positions if row.status == "open"]
            print(f"Wallet {w.id}: {len(open_rows)} open positions.")
            
            for row in open_rows:
                pos_out = _to_position(row, read)
                if pos_out.current_price is None or pos_out.current_price_at is None:
                    print(f"  mint: {pos_out.mint_address}, current_price: {pos_out.current_price}, current_price_at: {pos_out.current_price_at}")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperWallet
from app.paper.service import PaperWalletService
from app.paper.api import _to_position
from datetime import datetime, timezone

async def main():
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        wallets = list(await session.scalars(select(PaperWallet).where(PaperWallet.generation == 2)))
        print(f"Found {len(wallets)} Gen 2 wallets.")
        
        for w in wallets:
            service = PaperWalletService(session)
            async def mock_wallet(now=None, _w=w):
                return _w
            service.wallet = mock_wallet
            read = await service.read(now=now)
            
            open_rows = [row for row in read.positions if row.status == "open"]
            print(f"Wallet {w.id}: {len(open_rows)} open positions.")
            
            for row in open_rows:
                pos_out = _to_position(row, read)
                if not pos_out.current_price_at:
                    print(f"  Falsy current_price_at! mint: {pos_out.mint_address}, current_price: {pos_out.current_price}, current_price_at: {pos_out.current_price_at}")
                if not pos_out.current_price:
                    print(f"  Falsy current_price! mint: {pos_out.mint_address}, current_price: {pos_out.current_price}, current_price_at: {pos_out.current_price_at}")

if __name__ == "__main__":
    asyncio.run(main())

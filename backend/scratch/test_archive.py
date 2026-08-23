import asyncio
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperWallet
from app.paper.service import PaperWalletService
from app.paper.api import _to_position

async def main():
    async with SessionFactory() as session:
        service = PaperWalletService(session)
        wallets = await session.scalars(select(PaperWallet))
        
        for w in wallets:
            try:
                # read or read_archive
                if w.archived_at is None:
                    read = await service.read()
                else:
                    read = await service.read_archive(w.id)
                
                # simulate what api.py does
                open_pos = [p for p in read.positions if p.status == "open"]
                for p in open_pos:
                    out = _to_position(p, read)
                    if out.current_price_at is None:
                        print(f"Gen {w.generation}: Missing current_price_at for {p.mint_address}")
            except Exception as e:
                print(f"Gen {w.generation} error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

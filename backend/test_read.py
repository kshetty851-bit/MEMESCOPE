import asyncio
import time
from app.core.config import settings
from app.core.database import session_maker
from app.paper.service import PaperWalletService
from app.repositories.paper import PaperWalletRepository

async def main():
    async with session_maker() as session:
        wallet = await PaperWalletRepository(session).latest()
        if not wallet:
            print("No wallet")
            return
            
        svc = PaperWalletService(session)
        
        # Warmup
        await svc.read(wallet)
        
        t0 = time.time()
        await svc.read(wallet)
        t1 = time.time()
        print(f"Read took: {t1-t0:.4f}s")

if __name__ == "__main__":
    asyncio.run(main())

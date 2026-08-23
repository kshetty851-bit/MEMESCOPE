import asyncio
import time
from datetime import UTC, datetime

from app.db.session import async_session_maker
from app.paper.service import PaperWalletService

async def main():
    async with async_session_maker() as session:
        t0 = time.time()
        service = PaperWalletService(session)
        now = datetime.now(UTC)
        read = await service.read(now=now)
        t1 = time.time()
        print(f"Total time for read(): {t1 - t0:.3f}s")
        print(f"Open positions: {len([p for p in read.positions if p.status == 'open'])}")
        print(f"Closed positions: {len([p for p in read.positions if p.status == 'closed'])}")

if __name__ == "__main__":
    asyncio.run(main())

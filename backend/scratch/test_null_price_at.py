import asyncio
from datetime import datetime, timezone
from app.db.session import SessionFactory
from app.paper.api import list_positions

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        count = 0
        for p in result.items:
            if p.status == 'open' and p.current_price_at is None:
                print(f"NULL PRICE AT: {p.mint_address}")
                count += 1
        print(f"Total open missing current_price_at: {count}")

if __name__ == "__main__":
    asyncio.run(main())

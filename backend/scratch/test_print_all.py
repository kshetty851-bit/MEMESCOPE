import asyncio
from datetime import datetime, timezone
from app.db.session import SessionFactory
from app.paper.api import list_positions

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        print(f"Total returned: {len(result.items)}")
        for p in result.items:
            if p.status == 'open':
                print(f"Mint: {p.mint_address}, current_price_at: {p.current_price_at}")

if __name__ == "__main__":
    asyncio.run(main())

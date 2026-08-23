import asyncio
from app.db.session import SessionFactory
from app.paper.api import list_positions
import json

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        items = result.items
        
        open_items = [p for p in items if p.status == 'open']
        print(f"Total open: {len(open_items)}")
        
        for p in open_items:
            print(f"Mint: {p.mint_address}, Price: {p.current_price}, Price_At: {p.current_price_at}")

if __name__ == "__main__":
    asyncio.run(main())

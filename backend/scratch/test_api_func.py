import asyncio
from datetime import datetime, timezone
from app.db.session import SessionFactory
from app.paper.api import list_positions
from fastapi import Request

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        items = result.items
        waiting = []
        for p in items:
            if p.status == 'open' and not p.current_price_at:
                waiting.append(p)
        print(f"Total waiting: {len(waiting)}")
        for w in waiting:
            print(f"Waiting mint: {w.mint_address}")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from datetime import datetime, timezone
from app.db.session import SessionFactory
from app.paper.api import list_positions

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        json_data = result.model_dump(mode='json')
        count = 0
        for p in json_data['items']:
            if p['status'] == 'open' and p.get('current_price_at') is None:
                print(f"NULL IN JSON: {p['mint_address']}")
                count += 1
        print(f"Total null in JSON: {count}")

if __name__ == "__main__":
    asyncio.run(main())

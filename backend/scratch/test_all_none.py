import asyncio
from app.db.session import SessionFactory
from app.paper.api import list_positions

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        json_data = result.model_dump(mode='json')
        
        open_items = [p for p in json_data['items'] if p['status'] == 'open']
        print(f"Total open across all returned by API: {len(open_items)}")
        
        for p in open_items:
            if p.get('current_price') is None or p.get('current_price_at') is None:
                print(f"mint: {p['mint_address']}")
                print(f"  current_price: {p.get('current_price')}")
                print(f"  current_price_at: {p.get('current_price_at')}")

if __name__ == "__main__":
    asyncio.run(main())

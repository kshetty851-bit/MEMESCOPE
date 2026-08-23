import asyncio
from app.db.session import SessionFactory
from app.paper.api import list_positions

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        json_data = result.model_dump(mode='json')
        
        open_items = [p for p in json_data['items'] if p['status'] == 'open']
        print(f"Total open: {len(open_items)}")
        
        for p in open_items:
            if not p.get('current_price_at'):
                print(f"MISSING current_price_at: {p.get('mint_address')}")

if __name__ == "__main__":
    asyncio.run(main())

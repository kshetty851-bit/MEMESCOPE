import asyncio
from app.db.session import SessionFactory
from app.paper.api import list_positions

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        open_items = [p for p in result.items if p.status == 'open']
        print(f"Total open: {len(open_items)}")
        
        json_data = result.model_dump(mode='json')
        open_json = [p for p in json_data['items'] if p['status'] == 'open']
        
        for p in open_json:
            if p.get('current_price_at') is None:
                print(f"Missing current_price_at in JSON: {p['mint_address']}")
        print("Done checking JSON.")

if __name__ == "__main__":
    asyncio.run(main())

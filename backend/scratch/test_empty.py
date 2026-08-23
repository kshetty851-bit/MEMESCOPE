import asyncio
from app.db.session import SessionFactory
from app.paper.api import list_positions

async def main():
    async with SessionFactory() as session:
        result = await list_positions(session)
        json_data = result.model_dump(mode='json')
        for p in json_data['items']:
            if p['status'] == 'open':
                val = p.get('current_price_at')
                if not val:
                    print(f"FALSY current_price_at: {p['mint_address']} -> {repr(val)}")

if __name__ == "__main__":
    asyncio.run(main())

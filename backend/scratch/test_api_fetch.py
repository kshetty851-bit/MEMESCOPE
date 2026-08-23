import asyncio
import httpx
import json

async def main():
    async with httpx.AsyncClient() as client:
        r = await client.get('http://localhost:8000/api/v1/paper/positions')
        print(json.dumps(r.json(), indent=2))

if __name__ == "__main__":
    asyncio.run(main())

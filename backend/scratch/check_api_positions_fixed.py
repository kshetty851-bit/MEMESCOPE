import asyncio
from httpx import AsyncClient

async def main():
    async with AsyncClient(base_url="http://localhost:8000") as client:
        resp = await client.get("/api/v1/paper/positions", headers={"Authorization": "Bearer alpha-code"})
        if resp.status_code == 200:
            data = resp.json()
            positions = data.get("items", [])
            print(f"Total positions in endpoint: {len(positions)}")
            waiting = [p for p in positions if p.get("status") == "open" and not p.get("current_price_at")]
            for w in waiting:
                print(f"Waiting for liquidity: {w.get('symbol')} ({w.get('mint_address')})")
            print(f"Total waiting: {len(waiting)}")
        else:
            print(f"Failed: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    asyncio.run(main())

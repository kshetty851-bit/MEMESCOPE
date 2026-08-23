import asyncio
from fastapi.testclient import TestClient
from app.main import app

def main():
    client = TestClient(app)
    resp = client.get("/api/v1/paper/wallet", headers={"Authorization": "Bearer open"})
    if resp.status_code == 200:
        data = resp.json()
        positions = data.get("positions", [])
        print(f"Total positions: {len(positions)}")
        waiting = [p for p in positions if p.get("status") == "open" and not p.get("current_price_at")]
        for w in waiting:
            print(f"Waiting for liquidity: {w.get('symbol')} ({w.get('mint')})")
        print("Done")
    else:
        print(f"Failed: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    main()

import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionFactory

def main():
    client = TestClient(app)
    # the endpoint requires active wallet auth maybe? let's try with normal
    resp = client.get("/api/v1/paper/wallet", headers={"Authorization": "Bearer let-me-in"})
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

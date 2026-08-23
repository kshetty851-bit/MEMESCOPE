import asyncio
from fastapi.testclient import TestClient
from app.main import app

app.dependency_overrides.clear()
from app.api.auth import require_alpha
async def override_require_alpha():
    return None
app.dependency_overrides[require_alpha] = override_require_alpha

def main():
    client = TestClient(app)
    resp = client.get("/api/v1/paper/positions")
    if resp.status_code == 200:
        data = resp.json()
        items = data.get("items", [])
        count = 0
        for p in items:
            if p.get("status") == "open":
                if not p.get("current_price_at"):
                    print(f"FALSY current_price_at: {p.get('mint_address')}")
                    count += 1
        print(f"Total open with falsy current_price_at: {count}")
    else:
        print(f"Failed: {resp.status_code} {resp.text}")

if __name__ == "__main__":
    main()

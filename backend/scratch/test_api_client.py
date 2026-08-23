from fastapi.testclient import TestClient
from app.main import app
from app.dependencies.auth import get_alpha_code

# Override auth
app.dependency_overrides[get_alpha_code] = lambda: "mock"

client = TestClient(app)
response = client.get("/api/v1/paper/positions")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    items = data.get("items", [])
    open_items = [p for p in items if p.get("status") == "open"]
    print(f"Total open: {len(open_items)}")
    for p in open_items:
        if not p.get("current_price_at"):
            print(f"Waiting for liquidity: {p.get('mint_address')}")
    print("Done checking.")
else:
    print(response.text)

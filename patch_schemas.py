with open("backend/app/paper/schemas.py", "r") as f:
    content = f.read()

old_out = """    current_price: Decimal | None = None
    #: Percent from entry, on the current price. `None` follows `current_price`."""
new_out = """    current_price: Decimal | None = None
    current_market_cap: Decimal | None = None
    #: Percent from entry, on the current price. `None` follows `current_price`."""

if old_out in content:
    content = content.replace(old_out, new_out)
else:
    print("Could not find old out")

with open("backend/app/paper/schemas.py", "w") as f:
    f.write(content)

with open("backend/app/paper/api.py", "r") as f:
    content = f.read()

old_current = """    current = row.exit_price if closed else read.prices.get(row.mint_address)"""
new_current = """    current = row.exit_price if closed else read.prices.get(row.mint_address)
    current_mcap = getattr(row, "exit_market_cap", None) if closed else read.market_caps.get(row.mint_address)"""

if old_current in content:
    content = content.replace(old_current, new_current)
else:
    print("Could not find old current")

old_out = """        current_price=current,
        current_pct=_pct_from(row.entry_price, current),"""
new_out = """        current_price=current,
        current_market_cap=current_mcap,
        current_pct=_pct_from(row.entry_price, current),"""

if old_out in content:
    content = content.replace(old_out, new_out)
else:
    print("Could not find old out")

with open("backend/app/paper/api.py", "w") as f:
    f.write(content)

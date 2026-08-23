with open("frontend/src/types/paper.ts", "r") as f:
    content = f.read()

old_out = """  current_price: string | null;
  current_pct: string | null;"""
new_out = """  current_price: string | null;
  current_market_cap: string | null;
  current_pct: string | null;"""

if old_out in content:
    content = content.replace(old_out, new_out)
else:
    print("Could not find old out")

with open("frontend/src/types/paper.ts", "w") as f:
    f.write(content)

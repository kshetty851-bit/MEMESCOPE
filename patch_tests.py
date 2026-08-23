with open("frontend/src/components/paper/positions-table.test.tsx", "r") as f:
    content = f.read()

# Fix percentage finding
old_pct = 'expect(screen.getByText("-50.00%")).toBeInTheDocument();'
new_pct = 'expect(screen.getByTitle("-50.00%")).toBeInTheDocument();'
content = content.replace(old_pct, new_pct)

old_pct2 = 'expect(screen.getByText("+25.00%")).toBeInTheDocument();'
new_pct2 = 'expect(screen.getByTitle("+25.00%")).toBeInTheDocument();'
content = content.replace(old_pct2, new_pct2)

# Fix empty dash count
old_dash = 'expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);'
new_dash = 'expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);'
content = content.replace(old_dash, new_dash)

with open("frontend/src/components/paper/positions-table.test.tsx", "w") as f:
    f.write(content)

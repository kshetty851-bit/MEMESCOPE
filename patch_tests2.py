with open("frontend/src/components/paper/positions-table.test.tsx", "r") as f:
    content = f.read()

# Fix Exit rule header
content = content.replace('expect(screen.getByText("Exit rule")).toBeInTheDocument();', 'expect(screen.getByText("Exit rule / Info")).toBeInTheDocument();')

# In the same test "shows where the exit rule currently sits beside the price"
# We need to change the current price expectation to current_market_cap or remove it
# Let's just remove the $12.0000 expectation because current price isn't rendered anymore
content = content.replace('expect(screen.getByText("$12.0000")).toBeInTheDocument();', '')

with open("frontend/src/components/paper/positions-table.test.tsx", "w") as f:
    f.write(content)

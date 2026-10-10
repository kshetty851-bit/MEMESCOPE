import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BoostBook, BoostRuleBook, MinuteTable } from "./page";

const d = {
  started_at: "2026-10-10T12:00:00Z", backtest_from: "2026-09-30T20:00:00Z", boosts_since: "2026-10-10T12:00:00Z",
  hold_minutes: 4, ticket_usd: 50, capital_usd: 250, balance_usd: "518.49", coins_seen: 1454, coins_picked: 28, boosted_coins: 0,
  days: [], closed: [{ symbol: "PVE", mint: "M1", opened_at: "2026-10-08T20:31:00Z", closed_at: "2026-10-08T20:35:00Z",
                       pct: "250.8", pnl_usd: "125.4", pool_usd: "16081", rugged: false, profile: true, boosts: null, live: false }],
};

describe("Boost Lab", () => {
  it("shows the book's balance, profit and picks", () => {
    render(<BoostBook d={d} />);
    const b = screen.getByTestId("boost-book");
    expect(b).toHaveTextContent("+$268.49");
    expect(b).toHaveTextContent("+107% on $250.00");
    expect(b).toHaveTextContent("of 1454 the books bought");
    expect(screen.getByTestId("boost-closed")).toHaveTextContent("PVE");
  });

  it("states the rule and its catch", () => {
    render(<BoostRuleBook d={d} />);
    const t = screen.getByTestId("boost-rule-book");
    expect(t).toHaveTextContent("4 minutes after buying");
    expect(t).toHaveTextContent("the test, not the proof");
  });

  it("marks the book's own sell time in the minute table", () => {
    render(<MinuteTable capital={250} lines={[
      { minutes: 3, current: false, trades: 28, pnl_usd: "239.39", rugs: 1, lowest_usd: "248.15" },
      { minutes: 4, current: true, trades: 28, pnl_usd: "268.49", rugs: 1, lowest_usd: "250.00" }]} />);
    expect(screen.getByTestId("boost-minutes")).toHaveTextContent("4 min · the book");
  });
});

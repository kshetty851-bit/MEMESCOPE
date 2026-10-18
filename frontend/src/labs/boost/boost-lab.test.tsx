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

  it("shows the day-30 guess from the first trade", () => {
    const day = { n: 1, from: "2026-10-08T17:15:00Z", to: "2026-10-09T17:15:00Z", trades: 12, pnl_usd: "100",
                  pct: "40", rugs: 0, balance_usd: "350", running: false };
    render(<BoostBook d={{ ...d, first_trade_at: "2026-10-08T17:15:00Z", days: [{ ...day, n: 2, running: true }, day] }} />);
    expect(screen.getByTestId("day-30")).toHaveTextContent("Day 30 · expected");
  });

  it("states the rule and its catch", () => {
    render(<BoostRuleBook d={d} />);
    const t = screen.getByTestId("boost-rule-book");
    expect(t).toHaveTextContent("4 minutes after buying");
    expect(t).toHaveTextContent("the test, not the proof");
  });

  it("states the morning and selloff skips", () => {
    render(<BoostRuleBook d={{ ...d, skip_hours_dubai: [6, 12], morning_skipped: 24, max_sells_before: 20, sellers_skipped: 29 }} />);
    const t = screen.getByTestId("boost-rule-book");
    expect(t).toHaveTextContent("from 06:00 to 12:00 Dubai. 24 skipped so far.");
    expect(t).toHaveTextContent("more than 20 sells");
    expect(t).toHaveTextContent("flatter them");
  });

  it("states the first-seconds skip", () => {
    render(<BoostRuleBook d={{ ...d, min_entry_age_s: 19, too_early_skipped: 15 }} />);
    expect(screen.getByTestId("boost-rule-book")).toHaveTextContent("within 19 seconds of graduating");
  });

  it("states the cover-picture skip", () => {
    render(<BoostRuleBook d={{ ...d, cover_rule: true, cover_skipped: 8 }} />);
    expect(screen.getByTestId("boost-rule-book")).toHaveTextContent("no cover picture (the wide banner). 8 skipped so far.");
  });

  it("states the 18 Oct rules as a replay, not a live record", () => {
    render(<BoostRuleBook d={{ ...d, rules_selected_on: "2026-10-18", max_mcap_pool_ratio: "3.1", ratio_skipped: 40,
                               loss_streak_limit: 3, cooldown_minutes: 60, paused_skipped: 7 }} />);
    const t = screen.getByTestId("boost-rule-book");
    expect(t).toHaveTextContent("under 3.1 times its pool. A coin it cannot measure is skipped. 40 skipped so far.");
    expect(t).toHaveTextContent("After 3 trades in a row lose money, it buys nothing for 60 minutes");
    expect(t).toHaveTextContent("chosen on 18 October 2026");
    expect(t).toHaveTextContent("not what the book did at the time");
  });

  it("leaves the new rules out when the API has none", () => {
    render(<BoostRuleBook d={d} />);
    const t = screen.getByTestId("boost-rule-book");
    expect(t).not.toHaveTextContent("3.1 times");
    expect(t).not.toHaveTextContent("Replayed");
  });

  it("marks the book's own sell time in the minute table", () => {
    render(<MinuteTable capital={250} lines={[
      { minutes: 3, current: false, trades: 28, pnl_usd: "239.39", rugs: 1, lowest_usd: "248.15" },
      { minutes: 4, current: true, trades: 28, pnl_usd: "268.49", rugs: 1, lowest_usd: "250.00" }]} />);
    expect(screen.getByTestId("boost-minutes")).toHaveTextContent("4 min · the book");
    expect(screen.getByText(/each book replayed/)).toBeInTheDocument();
  });
});

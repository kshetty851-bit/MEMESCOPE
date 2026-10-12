import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BusyBook, BusyRuleBook, type BusyLab } from "./page";

const lab: BusyLab = {
  started_at: "2026-10-12T08:00:00Z", ticket_usd: 20, capital_usd: 200, hold_minutes: 3,
  stop_pct: 10, busy_min_txs: 100, balance_usd: "212.40", days: [], closed: [], open: [],
};

describe("Busy Pool Lab", () => {
  it("states the rule and the money", () => {
    render(<BusyRuleBook d={lab} />);
    const r = screen.getByTestId("busy-rule-book");
    expect(r).toHaveTextContent("100 or more trades");
    expect(r).toHaveTextContent("$20.00 per trade from $200.00");
  });
  it("shows the balance and the profit on $200", () => {
    render(<BusyBook d={lab} now={Date.parse("2026-10-12T09:00:00Z")} />);
    expect(screen.getByTestId("busy-book")).toHaveTextContent("+$12.40");
    expect(screen.getByTestId("busy-book")).toHaveTextContent("No trades yet");
  });
});

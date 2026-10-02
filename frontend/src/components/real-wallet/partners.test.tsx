import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PartnersCard, dayThirty, elapsed, type Partners } from "./partners";

const data: Partners = {
  started_at: "2026-09-28T11:00:00+00:00", capital_usd: "100.00", profit_usd: "11.50",
  balance_usd: "111.50", pct: "11.50", trades: 3, wins: 2, open: 1,
  partners: [
    { name: "Karthik", share: "0.5", put_in_usd: "50.00", profit_usd: "5.75", now_usd: "55.75" },
    { name: "Rafiq", share: "0.5", put_in_usd: "50.00", profit_usd: "5.75", now_usd: "55.75" },
  ],
  days: [
    { n: 2, from: "", to: "", running: true, trades: 1, pnl_usd: "10.00", pct: "9.85", balance_usd: "111.50" },
    { n: 1, from: "", to: "", running: false, trades: 2, pnl_usd: "1.50", pct: "1.50", balance_usd: "101.50" },
  ],
};

describe("Karthik & Rafiq's box", () => {
  it("shows each partner's profit and what they have now, and the days", () => {
    render(<PartnersCard data={data} />);
    const box = screen.getByTestId("partners");
    expect(box).toHaveTextContent("Karthik+$5.75put in $50.00 · now $55.75");
    expect(box).toHaveTextContent("Rafiq+$5.75put in $50.00 · now $55.75");
    expect(box).toHaveTextContent("$100.00 → $111.50");
    expect(box).toHaveTextContent("Day 2 · so far+$10.00" + "1 trades");
    expect(box).toHaveTextContent("Day 1+$1.502 trades");
    expect(box).not.toHaveTextContent("+9.85%");        // dollars only on the days
    expect(box).toHaveTextContent("since 28 Sep, 3:00 PM (Dubai)");
  });

  it("leads with what the wallet is worth now, in dollars and SOL", () => {
    const worth: Partners = {
      ...data, sol_usd: "116.61", value_pct: "37.63", open_cost_usd: "0.00",
      total_put_in_sol: "0.8457", total_value_usd: "137.63", total_value_profit_usd: "37.63",
      total_value_sol: "1.1803", total_value_profit_sol: "0.3227",
      partners: data.partners.map((p) => ({
        ...p, put_in_sol: "0.4229", value_usd: "68.82", value_profit_usd: "18.82",
        value_sol: "0.5901", value_profit_sol: "0.1614",
      })),
    };
    render(<PartnersCard data={worth} />);
    const box = screen.getByTestId("partners");
    expect(box).toHaveTextContent(
      "Karthik+$18.82+0.1614 SOLput in $50.00 (0.4229 SOL) · now $68.82 (0.5901 SOL)from trades +$5.75");
    expect(box).toHaveTextContent("Together+$37.63+0.3227 SOL$100.00 → $137.63 (1.1803 SOL) · +37.63%");
    expect(box).toHaveTextContent("($116.61 per SOL)");
  });
});

describe("the timer and day 30", () => {
  it("counts days, hours, minutes and seconds since the start", () => {
    const from = Date.parse("2026-09-28T11:00:00Z");
    expect(elapsed(from, from + ((4 * 24 + 7) * 3600 + 12 * 60 + 8) * 1000)).toBe("4d 07h 12m 08s");
    expect(elapsed(from, from - 5000)).toBe("0d 00h 00m 00s");
  });

  it("carries the gain's daily pace, straight-line, to day 30", () => {
    // $100 -> $120 in 4 days: $5 a day, so $250 at day 30.
    expect(dayThirty(100, 120, 4)).toBe(250);
    expect(dayThirty(100, 95, 2)).toBe(25);    // a loss carried the same way
    expect(dayThirty(100, 90, 2)).toBe(0);     // and never below nothing
    expect(dayThirty(100, 120, 0.5)).toBeNull();  // not before a full day
  });

  it("shows both on the box", () => {
    render(<PartnersCard data={data} />);
    expect(screen.getByTestId("partners-timer")).toHaveTextContent(/^\d+d \d\dh \d\dm \d\ds$/);
    expect(screen.getByTestId("partners-day30")).toHaveTextContent("$");
  });
});

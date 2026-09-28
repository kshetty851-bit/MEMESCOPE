import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PartnersCard, type Partners } from "./partners";

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
    expect(box).toHaveTextContent("Day 2 · so far+9.85%+$10.00 · 1 trades");
    expect(box).toHaveTextContent("Day 1+1.50%+$1.50 · 2 trades");
    expect(box).toHaveTextContent("since 28 Sep, 3:00 PM (Dubai)");
  });
});

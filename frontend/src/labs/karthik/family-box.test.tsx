import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FamilyBox } from "./page";

describe("three-wallet box", () => {
  it("shows the total and one line per month", () => {
    render(<FamilyBox f={{ wallets: 3, start_usd: 500, tickets_by_pool: [[150000, 100], [null, 25]], balance_usd: 4612.85, pnl_usd: 3112.85,
      months: [{ month: "2026-10", trades: 2790, rugs: 42, pnl_usd: 3112.85 },
               { month: "2026-11", trades: 10, rugs: 1, pnl_usd: -20 }] }} />);
    const box = screen.getByTestId("family-box");
    expect(box).toHaveTextContent("If 3 user wallets × $500");
    expect(box).toHaveTextContent("Oct 2026");
    expect(box).toHaveTextContent("Nov 2026");
    expect(box).toHaveTextContent("-$20");
  });
});

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SmallFirstView } from "./small-first";

describe("Small First Buy test box", () => {
  it("shows the total and one row per day", () => {
    render(<SmallFirstView d={{
      started_at: "2026-10-31T20:00:00+00:00", priced_until: "2026-11-05T00:00:00+00:00", ticket_usd: 5,
      trades: 3, wins: 2, rugs: 1, pnl_usd: 1.5,
      days: [{ day: "2026-11-02", trades: 1, wins: 0, rugs: 1, pnl_usd: -3 }, { day: "2026-11-01", trades: 2, wins: 2, rugs: 0, pnl_usd: 4.5 }],
      recent: [{ mint: "Mint1111", symbol: "ABC", graduated_at: "2026-11-02T10:00:00+00:00", ret: -0.6, pnl_usd: -3, held_s: 300, how: "5m", first_sol: 90, pool_sol: 95 }],
    }} />);
    expect(screen.getByText("+$1.50")).toBeTruthy();
    const days = screen.getByTestId("small-first-days");
    expect(within(days).getAllByRole("row")).toHaveLength(2);
    expect(within(days).getByText("−$3.00")).toBeTruthy();
    expect(screen.getByText("ABC")).toBeTruthy();
  });
});

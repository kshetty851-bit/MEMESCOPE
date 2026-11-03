import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RefusedDays } from "./page";

const coin = (day: number, symbol: string) => ({
  day, symbol, mint: `${symbol}mint`, opened_at: "2026-11-02T10:00:00Z", closed_at: "2026-11-02T10:10:00Z",
  pct: "-2.00", pnl_usd: "-1.00", pool_usd: "60000",
});

describe("refused coins", () => {
  it("opens a day's box onto the coins refused that day", () => {
    render(<RefusedDays total="-2" coins={[coin(2, "BBB"), coin(1, "AAA")]}
      days={[{ n: 2, running: true, trades: 1, rugs: 0, pnl_usd: "-1" }, { n: 1, running: false, trades: 1, rugs: 0, pnl_usd: "-1" }]} />);
    expect(screen.queryByTestId("refused-day-coins")).toBeNull();
    fireEvent.click(screen.getByTestId("refused-day-1"));
    const list = screen.getByTestId("refused-day-coins");
    expect(within(list).getByText(/AAA/)).toBeInTheDocument();
    expect(within(list).queryByText(/BBB/)).toBeNull();
  });
});

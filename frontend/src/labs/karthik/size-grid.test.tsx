import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SizeGrid } from "./page";
import type { KarthikBook } from "./types";

const cell = (balance: string, pnl: string, pct: string) => ({
  balance_usd: balance, pnl_usd: pnl, pnl_pct: pct, trades: 3, skipped: 0, rugs: 0, lowest_usd: balance,
});

const book = {
  started_at: "2026-09-30T20:00:00Z",
  whatif: {
    floors: [{ floor_usd: 75_000, book: true, replayed_below: false },
             { floor_usd: 100_000, cap_usd: 150_000, book: false, replayed_below: false }],
    sizes: [{ ticket_usd: 10, capital_usd: 100, current: false, cells: [cell("106.00", "6.00", "6.00"), cell("104.00", "4.00", "4.00")] }],
  },
} as unknown as KarthikBook;

describe("If each trade had been", () => {
  it("is one table from 1 Oct on six times the money, showing the balance", () => {
    render(<SizeGrid data={book} />);
    expect(screen.getByText(/If each trade had been — on 6x the money, from 1 Oct/)).toBeInTheDocument();
    const grid = screen.getByTestId("size-grid");
    expect(grid).toHaveTextContent("$10 on $100");
    expect(grid).toHaveTextContent("$106.00+$6.00 (+6.0%)");
    expect(grid).toHaveTextContent("$100k–$150k");
    expect(screen.queryByTestId("size-grid-wide")).toBeNull();
  });
});

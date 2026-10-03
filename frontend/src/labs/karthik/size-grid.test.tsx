import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SizeGrid } from "./page";
import type { KarthikBook } from "./types";

const cell = (balance: string, pnl: string, pct: string) => ({
  balance_usd: balance, pnl_usd: pnl, pnl_pct: pct, trades: 3, skipped: 0, rugs: 0, lowest_usd: balance,
});

const book = {
  started_at: "2026-09-23T12:00:00Z",
  whatif: {
    floors: [{ floor_usd: 75_000, book: true, replayed_below: false }],
    sizes: [{ ticket_usd: 10, capital_usd: 20, current: false, cells: [cell("26.00", "6.00", "30.00")] }],
    sizes_wide: [{ ticket_usd: 10, capital_usd: 100, current: false, cells: [cell("106.00", "6.00", "6.00")] }],
  },
} as unknown as KarthikBook;

describe("If each trade had been", () => {
  it("adds a second table on ten times the money, showing the balance", () => {
    render(<SizeGrid data={book} />);
    expect(screen.getByText("If each trade had been — on 10x the money")).toBeInTheDocument();
    const wide = screen.getByTestId("size-grid-wide");
    expect(wide).toHaveTextContent("$10 on $100");
    expect(wide).toHaveTextContent("$106.00+$6.00 (+6.0%)");
  });

  it("keeps the first table as it was", () => {
    render(<SizeGrid data={{ ...book, whatif: { ...book.whatif, sizes_wide: undefined } }} />);
    expect(screen.queryByTestId("size-grid-wide")).toBeNull();
    expect(screen.getByText("$10")).toBeInTheDocument();
  });
});

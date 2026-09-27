import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TradeList } from "./page";
import type { KarthikBook } from "./types";

const book = {
  hold_minutes: 5,
  skipped: 0,
  trades_list: [
    { symbol: "EVO", opened_at: "2026-09-24T10:00:00Z", closed_at: "2026-09-24T10:05:00Z", pct: "-100", pnl_usd: "-200", pool_usd: "146000" },
    { symbol: "WIN", mint: "WinMint1pump", opened_at: "2026-09-24T11:00:00Z", closed_at: "2026-09-24T11:05:00Z", pct: "2.1", pnl_usd: "4.2", pool_usd: "300000" },
  ],
} as unknown as KarthikBook;

describe("Karthik's Lab closed trades", () => {
  afterEach(() => window.localStorage.clear());

  it("starts folded with the count showing, opens and closes, and remembers", () => {
    const { unmount } = render(<TradeList data={book} />);
    expect(screen.getByText(/2 closed/)).toBeInTheDocument();
    expect(screen.queryByText("EVO")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show ▾" }));
    expect(screen.getByText("EVO")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide ▴" })).toHaveAttribute("aria-expanded", "true");
    unmount();

    // Left open, it opens again next time.
    render(<TradeList data={book} />);
    expect(screen.getByText("EVO")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide ▴" }));
    expect(screen.queryByText("EVO")).toBeNull();
  });

  it("links each coin to DexScreener to verify, with the date in Dubai", () => {
    window.localStorage.setItem("memescope.karthikTradesOpen", "open");
    render(<TradeList data={book} />);
    expect(screen.getByRole("link", { name: /WIN/ })).toHaveAttribute(
      "href", "https://dexscreener.com/solana/WinMint1pump");
    expect(screen.queryByRole("link", { name: /EVO/ })).toBeNull();   // no mint, no link
    expect(screen.getByText("24 Sept, 15:00")).toBeInTheDocument();  // 11:00 UTC is 15:00 Dubai
  });
});

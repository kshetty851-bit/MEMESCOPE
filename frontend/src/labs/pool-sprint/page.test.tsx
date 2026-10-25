import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PoolSprintContent, SprintTradeRow } from "./page";
import type { SprintBook } from "./types";

const hooks = vi.hoisted(() => ({ trades: vi.fn(), download: vi.fn() }));
vi.mock("./hooks", () => ({
  usePoolSprintBook: vi.fn(),
  usePoolSprintTrades: hooks.trades,
  downloadPoolSprintCsv: hooks.download,
}));

const book = {
  capital_usd: "2000",
  ticket_usd: "50",
  balance_usd: "2100.00",
  pnl_usd: "100.00",
  priced_pnl_usd: "150.00",
  pricing_reserve_usd: "50",
  lowest_usd: "1900.00",
  free_cash_usd: "2100.00",
  open_stake_usd: "0",
  lowest_cash_usd: "1850.00",
  signals: 3,
  trades: 3,
  closed: 2,
  open: 0,
  unpriced: 1,
  wins: 1,
  rugs: 1,
  skipped: 0,
  max_concurrent: 3,
  dex_exits: 1,
  candle_exits: 1,
  as_of: "2026-10-25T06:41:38Z",
  live_read_as_of: "2026-10-25T06:41:38Z",
  refreshing: false,
  refresh_error: false,
  days: [
    {
      date: "2026-10-01",
      n: 1,
      running: false,
      opened: 3,
      priced: 2,
      unpriced: 1,
      rugs: 1,
      skipped: 0,
      pnl_usd: "25",
      balance_usd: "2025",
    },
  ],
  start_dates: [],
  costs: [],
  sizes: [],
  bands: [],
} as unknown as SprintBook;

function setup() {
  hooks.trades.mockReturnValue({
    data: { total: 0, trades: [] },
    isLoading: false,
    isError: false,
  });
  render(<PoolSprintContent data={book} />);
}

describe("Pool Sprint paper account", () => {
  it("shows priced profit separately from the reserve-adjusted balance", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Pool Sprint Lab" })).toBeInTheDocument();
    expect(screen.getByText(/profit after that reserve is/)).toHaveTextContent("+$100.00");
    expect(screen.getByText(/Priced-trade profit is/)).toHaveTextContent("+$150.00");
    expect(screen.getByText("$1,850.00")).toBeInTheDocument();
    expect(screen.queryByText(/today.s SOL price/)).not.toBeInTheDocument();
    expect(screen.getByText(/no name, crew, volume/i)).toBeInTheDocument();
  });

  it("opens the clicked Dubai day and resets trade pagination", () => {
    setup();
    const firstDay = screen.getByRole("button", { name: /Day 1 \+\$25/ });
    fireEvent.click(firstDay);
    expect(hooks.trades).toHaveBeenLastCalledWith("2026-10-01", "all", 0);
    expect(screen.getByText("Trades settling 2026-10-01 · Dubai")).toBeInTheDocument();
  });

  it("does not turn an unpriced reserve into a reported rug or flat return", () => {
    render(
      <table>
        <tbody>
          <SprintTradeRow
            trade={{
              mint: "mint",
              symbol: null,
              opened_at: "2026-10-01T00:00:00Z",
              pool_usd: "15000",
              status: "unpriced",
              pct: null,
              pnl_usd: "-50",
              rugged: false,
            }}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText("Unpriced · stake reserved")).toBeInTheDocument();
    expect(screen.queryByText("+0.00%")).not.toBeInTheDocument();
    expect(screen.queryByText("· rug")).not.toBeInTheDocument();
  });

  it("labels candle estimates and observed rugs on actual priced outcomes", () => {
    render(
      <table>
        <tbody>
          <SprintTradeRow
            trade={{
              mint: "mint",
              symbol: "Test",
              pair: "pair",
              opened_at: "2026-10-01T00:00:00Z",
              pool_usd: "15000",
              status: "priced",
              pct: "-50",
              pnl_usd: "-25",
              source: "geckoterminal_candle_close",
              rugged: true,
            }}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText(/Minute candle close/)).toBeInTheDocument();
    expect(screen.getByText("· rug")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "https://dexscreener.com/solana/pair",
    );
  });
});

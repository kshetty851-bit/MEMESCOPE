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
  it("shows creator refusals separately and filters their entries", () => {
    hooks.trades.mockReturnValue({
      data: {
        total: 1,
        trades: [
          {
            mint: "blocked",
            symbol: "Test",
            creator: "creatorA",
            pair: "pair",
            opened_at: "2026-10-02T00:00:00Z",
            pool_usd: "15000",
            status: "creator_blocked",
          },
        ],
      },
      isLoading: false,
    });
    render(<PoolSprintContent data={{ ...book, creator_skipped: 2 }} />);
    expect(screen.getByText("Skipped · creator block")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show ▾" }));
    fireEvent.change(screen.getByLabelText("Trade status"), {
      target: { value: "creator_blocked" },
    });
    expect(hooks.trades).toHaveBeenLastCalledWith(null, "creator_blocked", 0);
    expect(screen.getByText("Skipped · creator rugged before")).toBeInTheDocument();
  });
  it("explains SOL-only exclusions and a cash-starved account", () => {
    hooks.trades.mockReturnValue({ data: { total: 0, trades: [] }, isLoading: false });
    render(
      <PoolSprintContent
        data={{
          ...book,
          free_cash_usd: "25.00",
          open: 0,
          excluded_non_sol: 2,
          unverified_pools: 1,
        }}
      />,
    );
    expect(screen.getByText(/SOL-only replay:/)).toHaveTextContent("2 non-SOL");
    expect(screen.getByText(/The account cannot fund another/)).toHaveTextContent("$25.00");
    expect(screen.getByText(/base mint must match/)).toBeInTheDocument();
  });
  it("shows priced profit separately from the reserve-adjusted balance", () => {
    setup();
    expect(screen.getByRole("heading", { name: "Pool Sprint Lab" })).toBeInTheDocument();
    expect(screen.getByText(/profit after that reserve is/)).toHaveTextContent("+$100.00");
    expect(screen.getByText(/Priced-trade profit is/)).toHaveTextContent("+$150.00");
    expect(screen.getByText("$1,850.00")).toBeInTheDocument();
    expect(screen.queryByText(/today.s SOL price/)).not.toBeInTheDocument();
    expect(screen.getByText(/no name, crew, volume/i)).toBeInTheDocument();
    expect(screen.getByText(/These are transaction counts/)).toBeInTheDocument();
    expect(
      screen.getByText(/Its delayed-entry research test lost money/),
    ).toBeInTheDocument();
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
              graduated_at: "2026-09-30T23:59:50Z",
              entry_buys: 13,
              entry_sells: 7,
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
    expect(screen.getByText("10s · 13/20 buys")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "https://dexscreener.com/solana/pair",
    );
  });
});

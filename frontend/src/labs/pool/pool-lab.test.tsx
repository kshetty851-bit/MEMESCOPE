import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FiftyKTables, TenKBookPanel, TenKRuleBook, TenKTable } from "./page";

const line = (t: number, pnl: string) => ({
  ticket_usd: t, capital_usd: 10 * t, balance_usd: String(10 * t + Number(pnl)), pnl_usd: pnl,
  pnl_pct: "0", trades: 12, rugs: 2, lowest_usd: String(10 * t),
});
const book = (pnl: number) => ({
  wallets: [{ name: "USER 1", balance_usd: 500 + pnl, pnl_usd: pnl, trades: 5, rugs: 1, lowest_usd: 480 }],
  total_usd: 500 + pnl, pnl_usd: pnl, trades: 5, uncapped_total_usd: 495, uncapped_pnl_usd: -5, coins: 7,
});

describe("Pool Lab", () => {
  it("shows every 10x size, live only since the reset", () => {
    render(<TenKTable data={{ live: [line(10, "-1.20")], live_coins: 2 }} />);
    const t = screen.getByTestId("pool-ten-k");
    expect(t).toHaveTextContent("$10 on $100");
    expect(t).toHaveTextContent("-$1.20");
    expect(t).not.toHaveTextContent("backtest");
  });

  it("shows ten wallets with a total, capped and uncapped", () => {
    render(<FiftyKTables data={{ backtest: book(12), live: book(-3), ticket_usd: 50, start_usd: 500, coin_cap_usd: 250 }} />);
    expect(screen.getByTestId("pool-fifty-back")).toHaveTextContent("USER 1$512.00+$12.00");
    expect(screen.getByTestId("pool-fifty-live")).toHaveTextContent("Total$497.00-$3.00");
    expect(screen.getByText(/5 wallets share each coin/)).toBeInTheDocument();
  });

  it("shows the $10k book's days with rugs, what it holds and what it closed", () => {
    const now = Date.parse("2026-10-05T18:00:00Z");
    render(<TenKBookPanel now={now} book={{
      ticket_usd: 50, capital_usd: 500, balance_usd: "512.40",
      days: [{ n: 1, from: "2026-10-05T16:45:00Z", to: "2026-10-06T16:45:00Z", running: true,
               trades: 3, rugs: 1, pnl_usd: "12.40", pct: "2.48", balance_usd: "512.40" }],
      open: [{ symbol: "OPN", mint: "MintOpen1", opened_at: "2026-10-05T17:58:00Z", pool_usd: "12000", pct_now: "-3.10" }],
      closed: [{ symbol: "RUG", mint: "MintRug1", opened_at: "2026-10-05T17:00:00Z", closed_at: "2026-10-05T17:05:00Z",
                 pct: "-90.00", pnl_usd: "-45.00", pool_usd: "15000", rugged: true }],
    }} />);
    expect(screen.getByTestId("day-1")).toHaveTextContent("3 trades · 1 rug");
    expect(screen.getByTestId("pool-open")).toHaveTextContent("OPN");
    expect(screen.getByTestId("pool-open")).toHaveTextContent("-3.10%");
    expect(screen.getByText(/Closed · 1 · 1 rugs/)).toBeInTheDocument();
    expect(screen.getByTestId("pool-closed")).toHaveTextContent("-$45.00");
    expect(screen.queryByTestId("trade-real")).toBeNull();
  });

  it("writes the $10k book's rules from its own numbers", () => {
    render(<TenKRuleBook book={{
      ticket_usd: 50, capital_usd: 500, balance_usd: "600", days: [], open: [],
      rules: { floor_usd: 10000, skip_pool_usd: [25000, 50000], quiet_max_txs: 100, max_entry_age_s: 120, hold_minutes: 3, stop_pct: 10, reaction_s: 3 },
      closed: [{ symbol: "A", mint: "M1", opened_at: "2026-10-06T00:00:00Z", closed_at: null, pct: "-90", pnl_usd: "-45", pool_usd: "15000", rugged: true },
               { symbol: "B", mint: "M2", opened_at: "2026-10-06T00:01:00Z", closed_at: null, pct: "5", pnl_usd: "2.5", pool_usd: "15000", rugged: false }],
    }} />);
    const t = screen.getByTestId("pool-rule-book");
    expect(t).toHaveTextContent("The pool must hold $10k or more.");
    expect(t).toHaveTextContent("No pools between $25k and $50k");
    expect(t).toHaveTextContent("Fewer than 100 trades");
    expect(t).toHaveTextContent("within 2 minutes");
    expect(t).toHaveTextContent("falls 10% below what it paid, it sells about 3 seconds later");
    expect(t).toHaveTextContent("3 minutes after buying, unless the stop-loss sold it first");
    expect(t).toHaveTextContent("So far 1 in 2 trades.");
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FiftyKTables, TenKBookPanel, TenKTable } from "./page";

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
});

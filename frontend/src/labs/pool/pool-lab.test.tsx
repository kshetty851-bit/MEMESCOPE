import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FiftyKTables, TenKTable } from "./page";

const line = (t: number, pnl: string) => ({
  ticket_usd: t, capital_usd: 10 * t, balance_usd: String(10 * t + Number(pnl)), pnl_usd: pnl,
  pnl_pct: "0", trades: 12, rugs: 2, lowest_usd: String(10 * t),
});
const book = (pnl: number) => ({
  wallets: [{ name: "USER 1", balance_usd: 500 + pnl, pnl_usd: pnl, trades: 5, rugs: 1, lowest_usd: 480 }],
  total_usd: 500 + pnl, pnl_usd: pnl, trades: 5, uncapped_total_usd: 495, uncapped_pnl_usd: -5, coins: 7,
});

describe("Pool Lab", () => {
  it("shows every 10x size with its backtest and live columns", () => {
    render(<TenKTable data={{ backtest: [line(10, "6.50")], live: [line(10, "-1.20")], backtest_coins: 30, live_coins: 2 }} />);
    const t = screen.getByTestId("pool-ten-k");
    expect(t).toHaveTextContent("$10 on $100");
    expect(t).toHaveTextContent("+$6.50");
    expect(t).toHaveTextContent("-$1.20");
  });

  it("shows ten wallets with a total, capped and uncapped", () => {
    render(<FiftyKTables data={{ backtest: book(12), live: book(-3), ticket_usd: 50, start_usd: 500, coin_cap_usd: 250 }} />);
    expect(screen.getByTestId("pool-fifty-back")).toHaveTextContent("USER 1$512.00+$12.00");
    expect(screen.getByTestId("pool-fifty-live")).toHaveTextContent("Total$497.00-$3.00");
    expect(screen.getByText(/5 wallets share each coin/)).toBeInTheDocument();
  });
});

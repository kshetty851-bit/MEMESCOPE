import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FiveMinTradesTable, pnlOf, pnlPctOf } from "./trades-panel";
import type { LabTrade } from "@/types/lab";

/**
 * The point of this view is that every row carries its own P&L and its own
 * full mint. The two ways it could lie: a percent computed off the wrong base,
 * and an unpriced open position rendered as break-even.
 */

const MINT = "FiveMinTradeMint1111111111111111111111111111";

function trade(overrides: Partial<LabTrade> = {}): LabTrade {
  return {
    id: "p1",
    strategy_id: "FM-01",
    strategy_name: "FIVEMIN-FLOW",
    mint: MINT,
    symbol: "FMT",
    token_name: "Five Min Token",
    status: "closed",
    opened_at: "2026-09-08T16:00:00+00:00",
    closed_at: "2026-09-08T16:05:10+00:00",
    held_hours: 5.17 / 60,
    size_usd: 5,
    entry_price: 0.001,
    entry_liquidity_usd: 120000,
    current_value_usd: 5.5,
    unrealised_pnl: null,
    realised_pnl: 0.5,
    exec_multiple: 1.1,
    peak_exec_multiple: 1.2,
    exit_reason: "time_exit",
    exit_proceeds_usd: 5.5,
    route_state: "ok",
    reached_125: false,
    reached_150: false,
    reached_200: false,
    partial_done: false,
    entry_source: "flow",
    ...overrides,
  };
}

describe("FiveMinTradesTable", () => {
  it("shows each trade's own P&L in dollars and percent, and the full mint", () => {
    render(
      <FiveMinTradesTable
        trades={[
          // +$0.50 on a $5 stake: +10%.
          trade(),
          // -$1.25 on $5: -25%.
          trade({ id: "p2", realised_pnl: -1.25, exit_proceeds_usd: 3.75 }),
          // Open, marked below cost by impact and fees: -3%.
          trade({
            id: "p3",
            status: "open",
            closed_at: null,
            realised_pnl: null,
            unrealised_pnl: -0.15,
            current_value_usd: 4.85,
            exit_proceeds_usd: null,
            exit_reason: null,
          }),
        ]}
      />,
    );

    expect(screen.getByText("+10.0%")).toBeInTheDocument();
    expect(screen.getByText("-25.0%")).toBeInTheDocument();
    expect(screen.getByText("-3.0%")).toBeInTheDocument();
    expect(screen.getByText("CLOSED — 2")).toBeInTheDocument();
    expect(screen.getByText("OPEN — 1")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 closed above cost/)).toBeInTheDocument();
    // Untruncated, in every row: this view exists so the address can be copied.
    expect(screen.getAllByText(MINT)).toHaveLength(3);
  });

  it("does not read an unpriced open position as break-even", () => {
    const unpriced = trade({ status: "open", realised_pnl: null, unrealised_pnl: null });
    expect(pnlOf(unpriced)).toBeNull();
    expect(pnlPctOf(unpriced)).toBeNull();
  });
});

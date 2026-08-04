import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PositionsTable } from "@/components/paper/positions-table";
import type { PaperPosition } from "@/types/paper";

/**
 * The positions table.
 *
 * What matters here is that a reader can check any trade against the published
 * rule without taking the result on trust: the stop and the target that were
 * fixed at entry sit beside the outcome, and losses are never filtered out or
 * softened.
 */

function position(overrides: Partial<PaperPosition> = {}): PaperPosition {
  return {
    mint_address: "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump",
    name: "Inward Unrest",
    symbol: "NWRDN",
    status: "open",
    opened_at: "2026-08-01T12:00:00Z",
    entry_rank: 3,
    entry_price: "10",
    size_usd: "100",
    quantity: "10",
    target_price: "20",
    stop_price: "5",
    expires_at: "2026-08-03T12:00:00Z",
    current_price: "12",
    current_pct: "20.00",
    peak_pct: "35.00",
    closed_at: null,
    exit_price: null,
    exit_reason: null,
    pnl_usd: "20.00",
    ...overrides,
  };
}

afterEach(cleanup);

describe("PositionsTable", () => {
  it("shows the levels fixed at entry beside the outcome", () => {
    // Without these a reader must take the exit on trust. With them, any trade
    // can be checked against the rule that produced it.
    render(<PositionsTable positions={[position()]} isPending={false} emptyLabel="none" />);

    expect(screen.getByText("Stop")).toBeInTheDocument();
    expect(screen.getByText("Target")).toBeInTheDocument();
    expect(screen.getByText("$5.0000")).toBeInTheDocument();
    expect(screen.getByText("$20.0000")).toBeInTheDocument();
  });

  it("names the rule that closed a trade", () => {
    render(
      <PositionsTable
        positions={[
          position({
            status: "closed",
            exit_reason: "stop",
            exit_price: "5",
            current_price: "5",
            current_pct: "-50.00",
            pnl_usd: "-50.00",
            closed_at: "2026-08-02T12:00:00Z",
          }),
        ]}
        isPending={false}
        emptyLabel="none"
      />,
    );

    expect(screen.getByText("Hit stop")).toBeInTheDocument();
    expect(screen.getByText("-$50.00")).toBeInTheDocument();
    expect(screen.getByText("-50.00%")).toBeInTheDocument();
  });

  it("never prints a raw exit code", () => {
    const { container } = render(
      <PositionsTable
        positions={[position({ status: "closed", exit_reason: "some_future_reason" })]}
        isPending={false}
        emptyLabel="none"
      />,
    );

    expect(container.textContent).not.toContain("some_future_reason");
    expect(screen.getByText("Closed")).toBeInTheDocument();
  });

  it("dashes an unpriced holding rather than valuing it at zero", () => {
    render(
      <PositionsTable
        positions={[position({ current_price: null, current_pct: null, pnl_usd: null })]}
        isPending={false}
        emptyLabel="none"
      />,
    );

    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });

  it("shows the rank the token held when it was bought", () => {
    // The entry rule is stated in terms of it, so a reader can check the trade
    // against the rule without reconstructing a past ranking.
    render(<PositionsTable positions={[position()]} isPending={false} emptyLabel="none" />);
    expect(screen.getByText("#3 at entry")).toBeInTheDocument();
  });

  it("keeps losers in the table beside winners", () => {
    render(
      <PositionsTable
        positions={[
          position({ mint_address: "win", symbol: "WIN", pnl_usd: "100.00" }),
          position({ mint_address: "loss", symbol: "LOSS", pnl_usd: "-50.00" }),
        ]}
        isPending={false}
        emptyLabel="none"
      />,
    );

    expect(screen.getByText("WIN")).toBeInTheDocument();
    expect(screen.getByText("LOSS")).toBeInTheDocument();
  });

  it("explains an empty table rather than showing nothing", () => {
    render(
      <PositionsTable positions={[]} isPending={false} emptyLabel="No position is open." />,
    );
    expect(screen.getByText("No position is open.")).toBeInTheDocument();
  });
});

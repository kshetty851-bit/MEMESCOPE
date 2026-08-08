import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AuditLog } from "@/components/paper/audit-log";
import type { PaperAuditEntry } from "@/types/paper";

/**
 * The permanent record.
 *
 * Almost every assertion here is about *refusal*. A log that renders an
 * uncosted trade's net return as zero, or drops the trade entirely, is stating
 * a result the platform did not measure — and this table is the one surface
 * where a reader is meant to be able to check a figure rather than trust it.
 */

function entry(overrides: Partial<PaperAuditEntry> = {}): PaperAuditEntry {
  return {
    mint_address: "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump",
    symbol: "NWRDN",
    entry_at: "2026-08-01T12:00:00Z",
    entry_price: "10",
    entry_market_cap: "124000",
    entry_liquidity_usd: "18000",
    size_usd: "100",
    quantity: "10",
    exit_at: "2026-08-01T18:00:00Z",
    exit_price: "15",
    exit_market_cap: "186000",
    exit_liquidity_usd: "18000",
    gross_return_usd: "50.0000",
    gross_return_pct: "50.0000",
    fee_usd: "0.7500",
    slippage_usd: "3.6111",
    net_return_usd: "45.6389",
    net_return_pct: "45.6389",
    cost_unavailable_reason: null,
    exit_reason: "stop",
    manual_action_at: null,
    strategy_id: "trailing_stop_25_v1",
    strategy_version: "1.0.0",
    wallet_generation: 2,
    hold_hours: "6.00",
    ...overrides,
  };
}

afterEach(cleanup);

describe("AuditLog", () => {
  it("shows gross beside net, and the components that separate them", () => {
    // Net alone hides how much the venue took; gross alone claims a return
    // nobody could have collected. Both, with the fee and impact between them.
    render(
      <AuditLog items={[entry()]} total={1} disclosure="disclosure" isPending={false} />,
    );

    expect(screen.getByText("+50.00%")).toBeInTheDocument();
    expect(screen.getByText("+45.64%")).toBeInTheDocument();
    expect(screen.getByText("$0.75")).toBeInTheDocument();
    expect(screen.getByText("$3.61")).toBeInTheDocument();
  });

  it("records the market cap at each end of the trade", () => {
    render(
      <AuditLog items={[entry()]} total={1} disclosure="disclosure" isPending={false} />,
    );

    expect(screen.getByText("$124.0K")).toBeInTheDocument();
    expect(screen.getByText("$186.0K")).toBeInTheDocument();
  });

  it("dashes an uncosted trade rather than reporting a zero cost", () => {
    // A bonding-curve pair reports no depth at all. Charging it nothing would
    // make the least tradeable trades look like the cheapest.
    render(
      <AuditLog
        items={[
          entry({
            fee_usd: null,
            slippage_usd: null,
            net_return_usd: null,
            net_return_pct: null,
            cost_unavailable_reason: "No pool depth was reported at one end.",
          }),
        ]}
        total={1}
        disclosure="disclosure"
        isPending={false}
      />,
    );

    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    // Gross still stands: the price did what it did.
    expect(screen.getByText("+50.00%")).toBeInTheDocument();
  });

  it("keeps losers in the record beside winners", () => {
    render(
      <AuditLog
        items={[
          entry({ mint_address: "win", symbol: "WIN" }),
          entry({
            mint_address: "loss",
            symbol: "LOSS",
            gross_return_pct: "-60.0000",
            net_return_pct: "-61.5000",
          }),
        ]}
        total={2}
        disclosure="disclosure"
        isPending={false}
      />,
    );

    expect(screen.getByText("WIN")).toBeInTheDocument();
    expect(screen.getByText("LOSS")).toBeInTheDocument();
    expect(screen.getByText("-60.00%")).toBeInTheDocument();
  });

  it("prints what the net figures exclude", () => {
    // The three refusals are as much a part of the model as the two inclusions.
    render(
      <AuditLog
        items={[entry()]}
        total={1}
        disclosure="They exclude priority fees and MEV."
        isPending={false}
      />,
    );

    expect(screen.getByText("They exclude priority fees and MEV.")).toBeInTheDocument();
  });

  it("says an empty record is empty rather than showing nothing", () => {
    render(<AuditLog items={[]} total={0} disclosure="d" isPending={false} />);

    expect(screen.getByText(/Nothing has closed yet/)).toBeInTheDocument();
  });

  it("says when it is showing a page of a longer record", () => {
    render(<AuditLog items={[entry()]} total={94} disclosure="d" isPending={false} />);

    expect(screen.getByText("Showing 1 of 94 recorded trades.")).toBeInTheDocument();
  });
});

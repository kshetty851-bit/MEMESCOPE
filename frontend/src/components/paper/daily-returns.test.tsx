import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DailyReturns } from "@/components/paper/daily-returns";
import type { PaperDailyReturn } from "@/types/paper";

afterEach(cleanup);

function day(overrides: Partial<PaperDailyReturn> = {}): PaperDailyReturn {
  return {
    date: "2026-08-16",
    completed_trades: 2,
    gross_pnl_usd: "25.00",
    gross_return_pct: "2.50",
    net_pnl_usd: "20.00",
    net_return_pct: "2.00",
    cost_unavailable_trades: 0,
    ...overrides,
  };
}

describe("DailyReturns", () => {
  it("shows each completed return with its UTC date", () => {
    render(
      <DailyReturns
        daily={[day()]}
        disclosure="Net figures include recorded fees and impact."
        isPending={false}
        isError={false}
      />,
    );

    expect(screen.getByText("2026-08-16")).toBeInTheDocument();
    expect(screen.getByText("$25.00")).toBeInTheDocument();
    expect(screen.getByText("$20.00")).toBeInTheDocument();
    expect(screen.getByText("+2.50%")).toBeInTheDocument();
    expect(screen.getByText("+2.00%")).toBeInTheDocument();
  });

  it("does not turn an uncosted day into a zero net return", () => {
    render(
      <DailyReturns
        daily={[
          day({ net_pnl_usd: null, net_return_pct: null, cost_unavailable_trades: 1 }),
        ]}
        disclosure="Net figures include recorded fees and impact."
        isPending={false}
        isError={false}
      />,
    );

    expect(screen.getByText("(1 uncosted)")).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });
});

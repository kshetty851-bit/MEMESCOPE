import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GraduationsSeen, PoolTrades } from "./page";

describe("graduations seen", () => {
  it("shows every graduation since the start, bought or not", () => {
    render(<GraduationsSeen count={6843} />);
    expect(screen.getByTestId("graduations-seen")).toHaveTextContent("6,843");
    expect(screen.getByText(/graduations seen/i)).toHaveTextContent("taken or not");
  });

  it("stays out of the way against an older API that does not send it", () => {
    const { container } = render(<GraduationsSeen count={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

const trade = (pool: string | null, pnl: string) => ({
  symbol: "X", opened_at: "2026-09-27T10:00:00Z", closed_at: null, pct: "1", pnl_usd: pnl, pool_usd: pool,
});

describe("trades by pool size", () => {
  it("counts the book's trades in each pool band, with what they made", () => {
    render(<PoolTrades trades={[trade("80000", "1.50"), trade("99999", "-0.50"), trade("620000", "2")]} />);
    const box = screen.getByTestId("pool-trades");
    expect(box).toHaveTextContent("$75k–$100k2+$1.00");
    expect(box).toHaveTextContent("$500k+1+$2.00");
    expect(box).not.toHaveTextContent("$100k–$150k");        // empty bands stay out
  });

  it("shows nothing before the first trade", () => {
    const { container } = render(<PoolTrades trades={[trade(null, "1")]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

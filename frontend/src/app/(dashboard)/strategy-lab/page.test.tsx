/**
 * Profit green, loss red — and the cases where neither is honest.
 *
 * The colour is read faster than the number beside it, so a cell painted the
 * wrong way is worse than one left plain: a reader scanning the tournament for
 * survivors takes the colour as the answer and moves on. These tests are
 * mostly about the readings that must stay NEUTRAL.
 */

import { describe, expect, it } from "vitest";

import { cellTone, toneOf } from "./page";
import type { LabStrategyRow } from "@/types/lab";

describe("toneOf", () => {
  it("paints a gain green and a loss red", () => {
    expect(toneOf(12.5)).toBe("text-up");
    expect(toneOf(-12.5)).toBe("text-down");
  });

  it("leaves an unmeasured figure uncoloured", () => {
    // A strategy with no closed trades has a null P&L and renders "—".
    // Green would read as a flat result rather than as an absent one.
    expect(toneOf(null)).toBe("");
    expect(toneOf(undefined)).toBe("");
    expect(toneOf(Number.NaN)).toBe("");
  });

  it("treats exactly zero as neutral, not as a win", () => {
    expect(toneOf(0)).toBe("");
  });
});

describe("cellTone", () => {
  const row = (over: Partial<LabStrategyRow> = {}) =>
    ({
      strategy_id: "V7-02", starting_equity: 100, equity: 100, net_pnl: 0,
      return_pct: 0, expectancy: 0, max_dd_pct: -40, win_pct: 20,
      profit_factor: 0.5, ...over,
    }) as LabStrategyRow;

  it("colours the P&L columns", () => {
    expect(cellTone(row({ net_pnl: 8 }), "net_pnl")).toBe("text-up");
    expect(cellTone(row({ return_pct: -9 }), "return_pct")).toBe("text-down");
    expect(cellTone(row({ expectancy: -0.4 }), "expectancy")).toBe("text-down");
  });

  it("judges equity against the money the strategy started with", () => {
    // Equity is always a positive number, so its own sign says nothing. A
    // wallet at $75 from a $100 start is a loss however positive $75 is.
    expect(cellTone(row({ equity: 75, starting_equity: 100 }), "equity")).toBe("text-down");
    expect(cellTone(row({ equity: 113, starting_equity: 100 }), "equity")).toBe("text-up");
    expect(cellTone(row({ equity: 100, starting_equity: 100 }), "equity")).toBe("");
  });

  it("leaves the columns that are not a profit or a loss alone", () => {
    // Max drawdown is always negative and would be permanently red; win rate
    // and PF are not P&L. Colouring most of the table stops the colour meaning
    // anything.
    for (const key of ["max_dd_pct", "win_pct", "profit_factor", "trades",
                       "cash", "starting_equity", "strategy_id"]) {
      expect(cellTone(row(), key)).toBe("");
    }
  });
});

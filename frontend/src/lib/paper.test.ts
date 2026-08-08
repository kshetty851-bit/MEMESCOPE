import { describe, expect, it } from "vitest";

import {
  PAPER_STATE_LABEL,
  byMint,
  exitLabel,
  hours,
  paperStateFor,
  pct,
  tone,
  usd,
} from "@/lib/paper";
import type { PaperPosition } from "@/types/paper";

/**
 * Paper wallet presentation.
 *
 * Almost every assertion is about *refusal*. A wallet that renders an unpriced
 * holding as $0, a missing win rate as 0%, or a token it never bought as
 * "available to trade" is stating a result it did not measure.
 */

function position(overrides: Partial<PaperPosition> = {}): PaperPosition {
  return {
    mint_address: "probe",
    name: "Probe",
    symbol: "PRB",
    status: "open",
    opened_at: "2026-08-01T12:00:00Z",
    entry_rank: 3,
    entry_price: "10",
    entry_observed_price: null,
    size_usd: "100",
    quantity: "10",
    entry_execution_model_version: null,
    entry_execution_price_impact_pct: null,
    entry_execution_fee_usd: null,
    entry_execution_route: null,
    entry_execution_quoted_at: null,
    entry_execution_confidence: null,
    entry_execution_fallback_reason: null,
    entry_market_cap: "124000",
    entry_liquidity_usd: "18000",
    target_price: null,
    stop_price: null,
    expires_at: null,
    trailing_drawdown: "0.2500",
    trailing_stop_price: "10.125",
    current_price: "12",
    current_pct: "20.00",
    current_price_at: "2026-08-01T12:00:00Z",
    peak_pct: "35.00",
    closed_at: null,
    exit_price: null,
    exit_observed_price: null,
    exit_execution_model_version: null,
    exit_execution_price_impact_pct: null,
    exit_execution_fee_usd: null,
    exit_execution_route: null,
    exit_execution_quoted_at: null,
    exit_execution_confidence: null,
    exit_execution_fallback_reason: null,
    exit_reason: null,
    manual_action_at: null,
    pnl_usd: "20.00",
    ...overrides,
  };
}

describe("usd", () => {
  it("returns null for absent money so callers render their own dash", () => {
    expect(usd(null)).toBeNull();
    expect(usd(undefined)).toBeNull();
    expect(usd("")).toBeNull();
  });

  it("distinguishes a real zero from an absent figure", () => {
    expect(usd("0")).toBe("$0.00");
    expect(usd(null)).toBeNull();
  });

  it("puts the sign outside the currency symbol", () => {
    expect(usd("-50.5")).toBe("-$50.50");
    expect(usd("1234.5")).toBe("$1,234.50");
  });
});

describe("pct", () => {
  it("is absent rather than a flat 0% when nothing was measured", () => {
    expect(pct(null)).toBeNull();
  });

  it("signs a gain and leaves a loss its own sign", () => {
    expect(pct("12.5")).toBe("+12.50%");
    expect(pct("-60.98")).toBe("-60.98%");
  });

  it("treats an unmeasured value as neutral, not as flat", () => {
    expect(tone(null)).toBe("neutral");
    expect(tone("0")).toBe("neutral");
    expect(tone("1")).toBe("positive");
    expect(tone("-1")).toBe("negative");
  });
});

describe("hours", () => {
  it("is absent when nothing has closed", () => {
    expect(hours(null)).toBeNull();
  });

  it("switches to days past two", () => {
    expect(hours("6")).toBe("6.0h");
    expect(hours("72")).toBe("3.0d");
  });
});

describe("exitLabel", () => {
  it("renders reasons in plain language", () => {
    expect(exitLabel("target")).toBe("Hit target");
    // "Trailing stop", not "Hit stop": the level moved with the price, and
    // calling it a stop would suggest a fixed one the strategy does not have.
    expect(exitLabel("stop")).toBe("Trailing stop");
    expect(exitLabel("expiry")).toBe("Held to expiry");
  });

  it("renders an unknown reason as nothing rather than as its code", () => {
    // Printing `liquidation` raw is worse than printing nothing, and a new
    // reason shipping before its label is a deploy away from correct.
    expect(exitLabel("liquidation")).toBeNull();
    expect(exitLabel(null)).toBeNull();
  });

  it("labels a manual paper override distinctly", () => {
    expect(exitLabel("manual")).toBe("Manual sell");
  });
});

describe("paperStateFor", () => {
  it("never describes an untraded token as actionable", () => {
    // The strategy enters on its own rule with no manual step, so "not held"
    // must never read as "available to buy".
    expect(paperStateFor(undefined)).toBe("not-held");
    expect(PAPER_STATE_LABEL["not-held"]).toBe("Not traded");
    expect(PAPER_STATE_LABEL["not-held"].toLowerCase()).not.toContain("buy");
  });

  it("distinguishes an open position from a finished one", () => {
    expect(paperStateFor(position())).toBe("open");
    expect(paperStateFor(position({ status: "closed" }))).toBe("closed");
  });
});

describe("byMint", () => {
  it("indexes positions so a page can ask about many tokens at once", () => {
    const index = byMint([position({ mint_address: "a" }), position({ mint_address: "b" })]);
    expect(index.get("a")?.mint_address).toBe("a");
    expect(index.get("missing")).toBeUndefined();
  });
});

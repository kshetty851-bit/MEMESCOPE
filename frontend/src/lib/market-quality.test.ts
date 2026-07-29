import { describe, expect, it } from "vitest";

import { QUALITY_LABEL, type MarketInput, assessMarket } from "@/lib/market-quality";

function input(over: Partial<MarketInput> = {}): MarketInput {
  return {
    scored: 100,
    strongOrBetter: 5,
    aboveEntry: 16,
    tracked: 33,
    deteriorating: 8,
    medianConfidence: 45,
    cloneWarnings: 4,
    ...over,
  };
}

describe("market quality", () => {
  it("calls a barren day weak and says so plainly", () => {
    const result = assessMarket(
      input({ strongOrBetter: 0, aboveEntry: 2, deteriorating: 25, medianConfidence: 20 }),
    );
    expect(["very_weak", "weak"]).toContain(result.quality);
    expect(result.summary).toContain("No project reached");
  });

  it("does not call a day good just because prices are up", () => {
    // Everything above entry, but nothing qualifies and confidence is low.
    // A broad rally lifts rugs too; breadth of price is not breadth of quality.
    const result = assessMarket(
      input({ strongOrBetter: 0, aboveEntry: 33, tracked: 33, medianConfidence: 15 }),
    );
    expect(["very_weak", "weak", "neutral"]).toContain(result.quality);
  });

  it("rates a genuinely good day highly", () => {
    const result = assessMarket(
      input({
        strongOrBetter: 18,
        aboveEntry: 30,
        tracked: 33,
        deteriorating: 1,
        medianConfidence: 82,
        cloneWarnings: 0,
      }),
    );
    expect(["strong", "exceptional"]).toContain(result.quality);
  });

  it("penalises a board full of deterioration", () => {
    const calm = assessMarket(input({ deteriorating: 0 }));
    const grim = assessMarket(input({ deteriorating: 33 }));
    expect(grim.score).toBeLessThan(calm.score);
  });

  it("penalises clone pressure", () => {
    const clean = assessMarket(input({ cloneWarnings: 0 }));
    const noisy = assessMarket(input({ cloneWarnings: 10 }));
    expect(noisy.score).toBeLessThan(clean.score);
  });

  it("returns the arithmetic so the verdict can be checked", () => {
    const result = assessMarket(input());
    const summed = result.factors.reduce((t, f) => t + f.points, 0);
    expect(result.score).toBe(summed);
    expect(result.factors).toHaveLength(5);
    for (const factor of result.factors) {
      expect(factor.points).toBeLessThanOrEqual(factor.of);
      expect(factor.points).toBeGreaterThanOrEqual(0);
    }
  });

  it("survives an empty platform without dividing by zero", () => {
    const result = assessMarket({
      scored: 0,
      strongOrBetter: 0,
      aboveEntry: 0,
      tracked: 0,
      deteriorating: 0,
      medianConfidence: 0,
      cloneWarnings: 0,
    });
    expect(Number.isFinite(result.score)).toBe(true);
    expect(QUALITY_LABEL[result.quality]).toBeTruthy();
  });

  it("is deterministic", () => {
    const probe = input();
    const runs = Array.from({ length: 50 }, () => assessMarket(probe).score);
    expect(new Set(runs).size).toBe(1);
  });
});

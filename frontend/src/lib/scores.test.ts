import { describe, expect, it } from "vitest";

import { GRADE_LABEL, GRADE_TONE, freshnessLabel, isElite, num, ratio } from "@/lib/scores";
import type { ScoreGrade, TokenScore } from "@/types/score";

/**
 * These helpers parse and label. None of them decides anything — that is the
 * point of the module, and the assertions below exist to keep it that way: if a
 * threshold that changes a verdict ever appears here, it belongs in the engine.
 */

describe("num", () => {
  it("parses a Decimal-as-string exactly", () => {
    expect(num("71.40")).toBe(71.4);
    expect(num("0.7824")).toBe(0.7824);
  });

  it("treats absent values as zero rather than NaN", () => {
    // A NaN would propagate silently into a meter width and render nothing.
    expect(num(null)).toBe(0);
    expect(num(undefined)).toBe(0);
    expect(num("")).toBe(0);
    expect(num("not-a-number")).toBe(0);
  });
});

describe("ratio", () => {
  it("converts a 0-100 backend figure to the 0-1 a Meter expects", () => {
    expect(ratio("65.00")).toBeCloseTo(0.65);
    expect(ratio("0")).toBe(0);
    expect(ratio("100")).toBe(1);
  });

  it("clamps, so a malformed value cannot overflow a meter", () => {
    expect(ratio("140")).toBe(1);
    expect(ratio("-20")).toBe(0);
  });
});

describe("grade presentation", () => {
  const grades: ScoreGrade[] = ["critical", "weak", "watch", "strong", "high_conviction"];

  it("labels and tones every grade the backend can return", () => {
    for (const grade of grades) {
      expect(GRADE_LABEL[grade]).toBeTruthy();
      expect(GRADE_TONE[grade]).toMatch(/^var\(--color-/);
    }
  });

  it("reserves gold for Elite by never assigning apex to a grade", () => {
    // Gold is a separate certification the grade alone never earns; if it
    // appeared here, a merely strong token would be painted like an Elite one.
    for (const grade of grades) {
      expect(GRADE_TONE[grade]).not.toContain("apex");
    }
  });
});

describe("freshnessLabel", () => {
  it("describes the backend's freshness figure without reinterpreting it", () => {
    expect(freshnessLabel(1)).toBe("Live");
    expect(freshnessLabel(0.75)).toBe("Recent");
    expect(freshnessLabel(0.2)).toBe("Ageing");
    expect(freshnessLabel(0)).toBe("Stale");
  });
});

describe("isElite", () => {
  it("reports the backend's certification and never infers one", () => {
    const base = { is_elite: false } as TokenScore;
    expect(isElite(base)).toBe(false);
    expect(isElite({ ...base, is_elite: true })).toBe(true);
    expect(isElite(null)).toBe(false);
    expect(isElite(undefined)).toBe(false);
  });
});

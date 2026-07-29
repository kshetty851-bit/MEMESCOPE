import { describe, expect, it } from "vitest";

import {
  CONVICTION_LABEL,
  CONVICTION_MEANING,
  CONVICTION_ORDER,
  CONVICTION_TONE,
  type Conviction,
  convictionLabel,
  convictionOf,
  convictionRank,
} from "@/lib/conviction";
import type { ScoreGrade } from "@/types/score";

const ALL_GRADES: ScoreGrade[] = [
  "critical",
  "weak",
  "watch",
  "strong",
  "high_conviction",
];

describe("conviction language", () => {
  it("maps every backend grade to a conviction", () => {
    // Total by construction: a grade added to the engine without a label here
    // would render as `undefined` on every card.
    for (const grade of ALL_GRADES) {
      expect(CONVICTION_LABEL[convictionOf(grade)]).toBeTruthy();
    }
  });

  it("preserves the engine's ordering", () => {
    const ranks = ALL_GRADES.map((grade) => convictionRank(convictionOf(grade)));
    // ALL_GRADES ascends in strength, so ranks must descend.
    expect(ranks).toEqual([...ranks].sort((a, b) => b - a));
  });

  it("reserves the top band for the backend's Elite flag", () => {
    // Elite is a stricter gate than any grade, so no grade alone reaches it.
    for (const grade of ALL_GRADES) {
      expect(convictionOf(grade)).not.toBe("very_high");
    }
    expect(convictionOf("high_conviction", true)).toBe("very_high");
  });

  it("lets Elite override a lower grade, because it is a separate gate", () => {
    expect(convictionOf("watch", true)).toBe("very_high");
  });

  it("gives the labels the brief asks for", () => {
    expect(convictionLabel("high_conviction")).toBe("High Conviction");
    expect(convictionLabel("strong")).toBe("Building");
    expect(convictionLabel("watch")).toBe("Watch Carefully");
    expect(convictionLabel("weak")).toBe("Speculative");
    expect(convictionLabel("critical")).toBe("Weak");
    expect(convictionLabel("high_conviction", true)).toBe("Very High Conviction");
  });

  it("explains every band, so no badge is unexplained", () => {
    for (const conviction of CONVICTION_ORDER) {
      const meaning = CONVICTION_MEANING[conviction];
      expect(meaning.length).toBeGreaterThan(40);
      expect(meaning.endsWith(".")).toBe(true);
    }
  });

  it("has a tone for every band", () => {
    for (const conviction of CONVICTION_ORDER) {
      expect(CONVICTION_TONE[conviction]).toMatch(/^var\(--color-/);
    }
  });

  it("uses gold only for Elite", () => {
    // The design system reserves gold exclusively for Elite certification.
    const gold = CONVICTION_TONE.very_high;
    const others = CONVICTION_ORDER.filter((c) => c !== "very_high");
    for (const conviction of others) {
      expect(CONVICTION_TONE[conviction]).not.toBe(gold);
    }
    expect(gold).toContain("apex");
  });

  it("contains no thresholds — the engine owns banding", () => {
    // A guard against the failure lib/intelligence.ts was deleted for. If this
    // module ever compares a score to a number, the frontend has started
    // holding an opinion the backend never issued.
    const order: readonly Conviction[] = CONVICTION_ORDER;
    expect(order).toHaveLength(6);
    expect(new Set(order).size).toBe(6);
  });
});

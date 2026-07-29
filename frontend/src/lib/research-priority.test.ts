import { describe, expect, it } from "vitest";

import {
  PRIORITY_LABEL,
  PRIORITY_MEANING,
  PRIORITY_ORDER,
  type PriorityInput,
  priorityRank,
  researchPriority,
} from "@/lib/research-priority";

function input(over: Partial<PriorityInput> = {}): PriorityInput {
  return {
    conviction: "building",
    mission: "orbit",
    confidence: 60,
    changeCount: 0,
    hasVeto: false,
    exitSeverity: "clear",
    cloneRisk: "none",
    ...over,
  };
}

describe("research priority", () => {
  it("ranks a veto Critical however well it scores elsewhere", () => {
    // Unexamined risk is the expensive kind. A strong band must not dilute it.
    const result = researchPriority(
      input({ hasVeto: true, conviction: "high", confidence: 90 }),
    );
    expect(result.priority).toBe("critical");
    expect(result.whyToday).toContain("vetoed");
  });

  it("ranks elevated Exit Watch Critical", () => {
    expect(researchPriority(input({ exitSeverity: "elevated" })).priority).toBe("critical");
  });

  it("ranks a deteriorating token above a healthy quiet one", () => {
    // The point of the whole module: information value, not desirability.
    const failing = researchPriority(input({ exitSeverity: "elevated", conviction: "weak" }));
    const healthy = researchPriority(input({ conviction: "high", confidence: 65 }));
    expect(priorityRank(failing.priority)).toBeLessThan(priorityRank(healthy.priority));
  });

  it("raises priority when something actually changed", () => {
    const still = researchPriority(input({ changeCount: 0 }));
    const moved = researchPriority(input({ changeCount: 3 }));
    expect(moved.score).toBeGreaterThan(still.score);
    expect(moved.whyToday).toContain("3 material changes");
  });

  it("lowers priority for a token it has barely observed", () => {
    const seen = researchPriority(input({ mission: "orbit" }));
    const unseen = researchPriority(input({ mission: "recon" }));
    expect(unseen.score).toBeLessThan(seen.score);
  });

  it("surfaces a high clone risk in the one sentence", () => {
    const result = researchPriority(input({ cloneRisk: "high" }));
    expect(result.whyToday).toContain("contested");
  });

  it("returns the arithmetic behind every ranking", () => {
    const result = researchPriority(input({ hasVeto: true, changeCount: 2 }));
    const summed = result.drivers.reduce((total, d) => total + d.points, 0);
    // Bounded to 0-100, so the sum matches unless it clipped.
    expect(result.score).toBe(Math.max(0, Math.min(100, summed)));
    expect(result.drivers.length).toBeGreaterThan(1);
  });

  it("gives every branch an observable sentence, never a generic one", () => {
    const cases: Partial<PriorityInput>[] = [
      { hasVeto: true },
      { exitSeverity: "elevated" },
      { exitSeverity: "watch" },
      { cloneRisk: "high" },
      { changeCount: 1 },
      { mission: "ascent" },
      { mission: "orbit" },
      { mission: "launch_window" },
      { mission: "re_entry" },
      { mission: "lost_contact" },
      { mission: "holding_pattern" },
      { mission: "recon" },
    ];

    for (const over of cases) {
      const { whyToday } = researchPriority(input(over));
      expect(whyToday.endsWith(".")).toBe(true);
      // No AI vocabulary, no hype, no advice.
      for (const banned of ["ai-powered", "smart", "buy", "sell", "moon", "guaranteed", "should"]) {
        expect(whyToday.toLowerCase()).not.toContain(banned);
      }
    }
  });

  it("is deterministic", () => {
    const probe = input({ changeCount: 2, cloneRisk: "moderate", confidence: 44 });
    const runs = Array.from({ length: 50 }, () => researchPriority(probe).score);
    expect(new Set(runs).size).toBe(1);
  });

  it("explains every band", () => {
    for (const priority of PRIORITY_ORDER) {
      expect(PRIORITY_LABEL[priority]).toBeTruthy();
      expect(PRIORITY_MEANING[priority].endsWith(".")).toBe(true);
    }
  });
});

import { describe, expect, it } from "vitest";

import {
  MISSION_LABEL,
  MISSION_MEANING,
  MISSION_ORDER,
  MISSION_RULE,
  type MissionInput,
  missionStatus,
} from "@/lib/mission";

function input(over: Partial<MissionInput> = {}): MissionInput {
  return {
    currentMultiple: 1.0,
    peakMultiple: 1.0,
    daysSinceDetection: 5,
    exitSeverity: "clear",
    hasVeto: false,
    observations: 48,
    ...over,
  };
}

describe("mission status", () => {
  it("withholds a view when there is too little history", () => {
    // Four observations is not a basis for any verdict, good or bad.
    expect(missionStatus(input({ observations: 4 }))).toBe("recon");
    expect(missionStatus(input({ observations: 4, currentMultiple: 5 }))).toBe("recon");
  });

  it("keeps recent detections provisional", () => {
    expect(missionStatus(input({ daysSinceDetection: 0.2, currentMultiple: 1.4 })))
      .toBe("launch_window");
  });

  it("calls a token holding its high Ascent", () => {
    expect(missionStatus(input({ currentMultiple: 2.5, peakMultiple: 2.6 }))).toBe("ascent");
  });

  it("calls a token that kept some of the move Orbit", () => {
    expect(missionStatus(input({ currentMultiple: 1.4, peakMultiple: 2.6 }))).toBe("orbit");
  });

  it("calls a flat token a Holding Pattern", () => {
    expect(missionStatus(input({ currentMultiple: 0.99, peakMultiple: 1.01 })))
      .toBe("holding_pattern");
  });

  it("calls a token below entry but not collapsed Re-entry", () => {
    expect(missionStatus(input({ currentMultiple: 0.8, peakMultiple: 1.2 }))).toBe("re_entry");
  });

  it("never lets a collapsing token read as Ascent", () => {
    // The live worst case: peaked at 5.84x, now 0.08x. Its multiple is not
    // above 1, but the ordering matters even when it is.
    expect(missionStatus(input({ currentMultiple: 0.08, peakMultiple: 5.84 })))
      .toBe("lost_contact");
    // Still above detection, but 96% off its peak — the drawdown wins.
    expect(missionStatus(input({ currentMultiple: 1.1, peakMultiple: 30 })))
      .toBe("lost_contact");
  });

  it("lets a veto override an otherwise healthy arc", () => {
    // A veto caps the score outright; the journey position must not paper
    // over it.
    expect(missionStatus(input({ currentMultiple: 2.5, peakMultiple: 2.5, hasVeto: true })))
      .toBe("lost_contact");
  });

  it("lets elevated Exit Watch override an otherwise healthy arc", () => {
    expect(
      missionStatus(input({ currentMultiple: 2.5, peakMultiple: 2.5, exitSeverity: "elevated" })),
    ).toBe("lost_contact");
  });

  it("still withholds a verdict on a vetoed token with no history", () => {
    // Recon outranks Lost Contact: without observations there is no basis
    // for either, and declaring a token lost on four points invents certainty.
    expect(missionStatus(input({ observations: 3, hasVeto: true }))).toBe("recon");
  });

  it("is total — every state is reachable and labelled", () => {
    const reached = new Set([
      missionStatus(input({ observations: 2 })),
      missionStatus(input({ daysSinceDetection: 0.1 })),
      missionStatus(input({ currentMultiple: 2.5, peakMultiple: 2.6 })),
      missionStatus(input({ currentMultiple: 1.4, peakMultiple: 2.6 })),
      missionStatus(input({ currentMultiple: 0.99 })),
      missionStatus(input({ currentMultiple: 0.8, peakMultiple: 1.2 })),
      missionStatus(input({ hasVeto: true })),
    ]);
    expect(reached.size).toBe(7);
    for (const state of MISSION_ORDER) {
      expect(MISSION_LABEL[state]).toBeTruthy();
      expect(MISSION_MEANING[state].endsWith(".")).toBe(true);
      expect(MISSION_RULE[state].endsWith(".")).toBe(true);
    }
  });

  it("is deterministic — same input, same state, every time", () => {
    const probe = input({ currentMultiple: 1.73, peakMultiple: 2.02 });
    const runs = Array.from({ length: 50 }, () => missionStatus(probe));
    expect(new Set(runs).size).toBe(1);
  });

  it("never describes conviction", () => {
    // The engine owns "is this good". These labels must not restate it, or
    // the two can disagree about the same token.
    const words = Object.values(MISSION_LABEL).join(" ").toLowerCase();
    for (const banned of ["conviction", "strong", "weak", "buy", "sell"]) {
      expect(words).not.toContain(banned);
    }
  });
});

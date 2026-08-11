import { describe, expect, it } from "vitest";

import {
  COUNTDOWN_FROM,
  FLIGHT_MS,
  LAUNCH_TIMELINE,
  REDUCED_TIMELINE,
  atOrAfter,
  launchDurations,
} from "@/lib/launch";

describe("launch timeline", () => {
  it("always ends by entering the application", () => {
    expect(LAUNCH_TIMELINE.at(-1)?.phase).toBe("enter");
    expect(REDUCED_TIMELINE.at(-1)?.phase).toBe("enter");
  });

  it("counts down from five to one, one digit per step", () => {
    const digits = LAUNCH_TIMELINE.filter((step) => step.phase === "countdown").map(
      (step) => step.count,
    );
    expect(digits).toEqual([5, 4, 3, 2, 1]);
    expect(digits).toHaveLength(COUNTDOWN_FROM);
  });

  it("keeps the flight between four and seven seconds", () => {
    // Long enough to feel like travel, short enough that a repeat visitor is
    // not held hostage by it.
    expect(FLIGHT_MS).toBeGreaterThanOrEqual(4_000);
    expect(FLIGHT_MS).toBeLessThanOrEqual(7_000);
  });

  it("gives reduced motion the confirmation without the ride", () => {
    expect(REDUCED_TIMELINE.map((step) => step.phase)).toEqual(["approved", "enter"]);
  });

  it("latches cumulative scene state forward, never backward", () => {
    expect(atOrAfter("flight", "ignition")).toBe(true);
    expect(atOrAfter("ignition", "ignition")).toBe(true);
    expect(atOrAfter("countdown", "ignition")).toBe(false);
    // Gate states are not part of the flight and must never light the engine.
    expect(atOrAfter("denied", "approved")).toBe(false);
    expect(atOrAfter("validating", "approved")).toBe(false);
  });

  it("publishes a flight duration CSS matches the timeline on", () => {
    expect(launchDurations()["--hu-flight"]).toBe(`${FLIGHT_MS}ms`);
    expect(launchDurations()["--hu-countdown"]).toBe(`${COUNTDOWN_FROM * 700}ms`);
  });
});

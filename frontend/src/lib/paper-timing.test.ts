import { describe, expect, it } from "vitest";

import { clock, entryDelaySeconds, epoch, formatDelay, stamp } from "@/lib/paper";

/**
 * DETECTION → ENTRY TIMING
 *
 * The delay printed on the track record is a subtraction between two stored
 * moments, so the only way it lies is by inventing one of them. Every absence
 * case is asserted here, because the failure this guards against renders as a
 * confident "+0s" rather than as an error.
 */
describe("clock", () => {
  it("renders a stored moment as a 24-hour wall clock", () => {
    expect(clock("2026-08-22T12:14:32Z")).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it("has nothing to say about a moment that was never stored", () => {
    expect(clock(null)).toBeNull();
    expect(clock(undefined)).toBeNull();
    expect(clock("")).toBeNull();
  });

  it("refuses a malformed timestamp rather than printing Invalid Date", () => {
    expect(clock("not-a-timestamp")).toBeNull();
  });
});

describe("stamp", () => {
  it("carries the unambiguous UTC form beside the local one", () => {
    const value = stamp("2026-08-22T12:14:32Z");
    expect(value).toContain("2026-08-22 12:14:32Z");
  });

  it("stays absent when the moment is", () => {
    expect(stamp(null)).toBeNull();
    expect(stamp("nonsense")).toBeNull();
  });
});

describe("epoch", () => {
  it("is the sort key for a column of times", () => {
    expect(epoch("2026-08-22T12:14:32Z")).toBe(Date.parse("2026-08-22T12:14:32Z"));
  });

  it("is null for an absent moment, so such rows sort last rather than first", () => {
    expect(epoch(null)).toBeNull();
    expect(epoch("nope")).toBeNull();
  });
});

describe("entryDelaySeconds", () => {
  it("measures detection to entry", () => {
    expect(
      entryDelaySeconds("2026-08-22T12:14:32Z", "2026-08-22T12:37:05Z"),
    ).toBe(1353);
  });

  it("withholds the delay when detection was never stored", () => {
    // The bug this exists to prevent: falling back to the entry time would make
    // every unmeasurable row read "+0s", which looks like a fast entry.
    expect(entryDelaySeconds(null, "2026-08-22T12:37:05Z")).toBeNull();
    expect(entryDelaySeconds(undefined, "2026-08-22T12:37:05Z")).toBeNull();
  });

  it("withholds the delay when there is no entry", () => {
    expect(entryDelaySeconds("2026-08-22T12:14:32Z", null)).toBeNull();
  });

  it("does not clamp an entry recorded before its own detection", () => {
    expect(
      entryDelaySeconds("2026-08-22T12:37:05Z", "2026-08-22T12:14:32Z"),
    ).toBe(-1353);
  });
});

describe("formatDelay", () => {
  it("matches the published example", () => {
    expect(formatDelay(1353)).toBe("+22m 33s");
  });

  it("scales through seconds, minutes, hours and days", () => {
    expect(formatDelay(0)).toBe("+0s");
    expect(formatDelay(45)).toBe("+45s");
    expect(formatDelay(60)).toBe("+1m 00s");
    expect(formatDelay(3600)).toBe("+1h 00m");
    expect(formatDelay(3600 + 7 * 60)).toBe("+1h 07m");
    expect(formatDelay(86_400 + 4 * 3600)).toBe("+1d 4h");
  });

  it("shows a negative delay as negative, because it is a data fault worth seeing", () => {
    expect(formatDelay(-1353)).toBe("−22m 33s");
  });

  it("prints nothing when there is nothing to print", () => {
    expect(formatDelay(null)).toBeNull();
    expect(formatDelay(Number.NaN)).toBeNull();
  });
});

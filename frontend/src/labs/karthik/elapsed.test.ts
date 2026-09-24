import { describe, expect, it } from "vitest";

import { formatElapsed, pctOfCapital } from "./page";

/**
 * The timer reads a duration, and a duration is the one number on this page
 * nobody can sanity-check by eye: 90 minutes and 1h 30m look equally plausible
 * printed wrong. These pin the rollovers.
 */
describe("formatElapsed", () => {
  it("pads to a clock before the first day", () => {
    expect(formatElapsed(0)).toBe("00:00:00");
    expect(formatElapsed(9 * 1000)).toBe("00:00:09");
    expect(formatElapsed((60 + 5) * 1000)).toBe("00:01:05");
    expect(formatElapsed(3600 * 1000)).toBe("01:00:00");
  });

  it("takes the day out of the clock once there is one", () => {
    expect(formatElapsed(86_400 * 1000)).toBe("1d 00:00:00");
    expect(formatElapsed((86_400 + 3661) * 1000)).toBe("1d 01:01:01");
    expect(formatElapsed(30 * 86_400 * 1000)).toBe("30d 00:00:00");
  });

  it("says so rather than counting backwards before the start", () => {
    expect(formatElapsed(-5000)).toBe("not started yet");
  });
});

/**
 * The percentage is the number Karthik reads first, and it is a percentage OF
 * THE STARTING CAPITAL -- not of the current balance, which would shrink the
 * headline every time the book made money.
 */
describe("pctOfCapital", () => {
  it("measures against what the book started with", () => {
    expect(pctOfCapital(72.45, 500)).toBe("+14.49%");
    expect(pctOfCapital(-50, 500)).toBe("-10.00%");
    expect(pctOfCapital(0, 500)).toBe("+0.00%");
  });

  it("takes the strings the API sends, not just numbers", () => {
    expect(pctOfCapital("72.45", "500")).toBe("+14.49%");
  });

  it("refuses to divide by a capital of zero", () => {
    expect(pctOfCapital(10, 0)).toBe("—");
    expect(pctOfCapital(null, 500)).toBe("—");
  });
});

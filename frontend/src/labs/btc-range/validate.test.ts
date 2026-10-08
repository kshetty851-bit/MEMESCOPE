import { describe, expect, it } from "vitest";

import { config } from "./fixtures";
import { defaultWindow, validateField, validateWindow, windowToIso } from "./validate";

const bounds = config().bounds;

describe("validateField", () => {
  it("accepts a value inside the bounds and rejects outside them", () => {
    expect(validateField(bounds.lookback, "96")).toBeNull();
    expect(validateField(bounds.lookback, "23")).toMatch(/at least 24/);
    expect(validateField(bounds.lookback, "501")).toMatch(/at most 500/);
  });

  it("requires whole numbers for ints and any number for decimals", () => {
    expect(validateField(bounds.lookback, "96.5")).toMatch(/whole number/);
    expect(validateField(bounds.entry_zone, "0.25")).toBeNull();
    expect(validateField(bounds.entry_zone, "0.5")).toMatch(/at most 0.45/);
  });

  it("rejects empty and non-numeric input", () => {
    expect(validateField(bounds.lookback, "")).toMatch(/Enter a value/);
    expect(validateField(bounds.lookback, "abc")).toMatch(/Enter a number/);
  });

  it("never fails a bool", () => {
    expect(validateField(bounds.allow_long, false)).toBeNull();
  });
});

describe("window", () => {
  it("defaults to the last 30 days of stored data, or less if fewer", () => {
    expect(defaultWindow("2026-08-01T00:00:00Z", "2026-10-08T03:00:00Z")).toEqual({
      start: "2026-09-08",
      end: "2026-10-08",
    });
    expect(defaultWindow("2026-10-01T00:00:00Z", "2026-10-08T03:00:00Z").start).toBe(
      "2026-10-01",
    );
    expect(defaultWindow(null, null)).toEqual({ start: "", end: "" });
  });

  it("bounds the dates by the stored data and orders them", () => {
    const f = "2026-08-01T00:00:00Z";
    const l = "2026-10-08T03:00:00Z";
    expect(validateWindow("2026-09-01", "2026-10-01", f, l)).toEqual({
      start: null,
      end: null,
    });
    expect(validateWindow("2026-07-01", "2026-10-01", f, l).start).toMatch(
      /begin on 2026-08-01/,
    );
    expect(validateWindow("2026-09-01", "2026-11-01", f, l).end).toMatch(
      /end on 2026-10-08/,
    );
    expect(validateWindow("2026-10-05", "2026-10-01", f, l).end).toMatch(/on or after/);
  });

  it("clamps the posted instants to the data", () => {
    const f = "2026-08-01T12:00:00Z";
    const l = "2026-10-08T03:00:00Z";
    expect(windowToIso("2026-08-01", "2026-10-08", f, l)).toEqual({ start: f, end: l });
    expect(windowToIso("2026-09-01", "2026-09-30", f, l)).toEqual({
      start: "2026-09-01T00:00:00Z",
      end: "2026-09-30T23:59:59Z",
    });
  });
});

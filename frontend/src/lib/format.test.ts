import { afterEach, describe, expect, it, vi } from "vitest";

import { formatAge, formatCount, formatPrice, formatUsd, shortenAddress } from "@/lib/format";

afterEach(() => {
  vi.useRealTimers();
});

describe("formatUsd", () => {
  it("compacts large magnitudes", () => {
    expect(formatUsd("1234")).toBe("$1.2K");
    expect(formatUsd("2500000")).toBe("$2.50M");
    expect(formatUsd("3200000000")).toBe("$3.20B");
  });

  it("keeps small amounts readable", () => {
    expect(formatUsd("12.5")).toBe("$12.50");
    expect(formatUsd("0.25")).toBe("$0.2500");
    expect(formatUsd("0")).toBe("$0");
  });

  it("renders an em dash for missing values", () => {
    expect(formatUsd(null)).toBe("—");
    expect(formatUsd(undefined)).toBe("—");
    expect(formatUsd("")).toBe("—");
  });

  it("does not crash on junk", () => {
    expect(formatUsd("not-a-number")).toBe("—");
  });
});

describe("formatPrice", () => {
  it("uses exponential notation below fixed-notation readability", () => {
    // Meme coin prices routinely sit here; fixed notation would render "$0.0000".
    expect(formatPrice("0.000000123")).toBe("$1.230e-7");
  });

  it("uses fixed notation for larger prices", () => {
    expect(formatPrice("1.5")).toBe("$1.5000");
    expect(formatPrice("0.001234")).toBe("$0.001234");
  });

  it("accepts the full precision the API sends without throwing", () => {
    expect(formatPrice("0.000000000123456789")).toMatch(/e-/);
  });
});

describe("formatCount", () => {
  it("groups thousands", () => {
    expect(formatCount(7528)).toBe("7,528");
  });

  it("distinguishes zero from missing", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(null)).toBe("—");
  });
});

describe("formatAge", () => {
  it("scales the unit with elapsed time", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-27T12:00:00Z"));

    expect(formatAge("2026-07-27T11:59:15Z")).toBe("45s");
    expect(formatAge("2026-07-27T11:48:00Z")).toBe("12m");
    expect(formatAge("2026-07-27T09:00:00Z")).toBe("3h");
    expect(formatAge("2026-07-22T12:00:00Z")).toBe("5d");
  });

  it("clamps future timestamps to zero rather than going negative", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-27T12:00:00Z"));
    expect(formatAge("2026-07-27T12:05:00Z")).toBe("0s");
  });

  it("renders an em dash for missing values", () => {
    expect(formatAge(null)).toBe("—");
  });
});

describe("shortenAddress", () => {
  it("elides the middle of long addresses", () => {
    expect(shortenAddress("HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump", 5, 5)).toBe(
      "HHbRJ…wpump",
    );
  });

  it("leaves short values intact", () => {
    expect(shortenAddress("abc")).toBe("abc");
  });

  it("renders an em dash for missing values", () => {
    expect(shortenAddress(null)).toBe("—");
  });
});

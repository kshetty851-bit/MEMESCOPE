import { describe, expect, it } from "vitest";

import {
  FRESHNESS_THRESHOLDS,
  ageLabel,
  bandFor,
  freshnessOf,
  newestOf,
  shortMint,
} from "@/lib/freshness";

/**
 * Freshness.
 *
 * The bands are the product's claim about its own data, so they are asserted at
 * their boundaries rather than in the middle. The rest is refusal: an unpriced
 * token is not a stale one, a clock disagreement is not a price from the
 * future, and nothing here ever says "live".
 */

const NOW = new Date("2026-08-04T12:00:00Z").getTime();
const at = (secondsAgo: number) =>
  new Date(NOW - secondsAgo * 1000).toISOString();

describe("bandFor", () => {
  it("names each band at its published boundary", () => {
    expect(bandFor(0)).toBe("fresh");
    expect(bandFor(FRESHNESS_THRESHOLDS.fresh - 1)).toBe("fresh");
    expect(bandFor(FRESHNESS_THRESHOLDS.fresh)).toBe("normal");
    expect(bandFor(FRESHNESS_THRESHOLDS.normal - 1)).toBe("normal");
    expect(bandFor(FRESHNESS_THRESHOLDS.normal)).toBe("ageing");
    expect(bandFor(FRESHNESS_THRESHOLDS.ageing - 1)).toBe("ageing");
    expect(bandFor(FRESHNESS_THRESHOLDS.ageing)).toBe("stale");
  });

  it("puts the measured Top 10 average in the fresh band", () => {
    // 7 seconds, measured after the priority lane landed.
    expect(bandFor(7)).toBe("fresh");
  });

  it("puts the pre-lane worst case in the stale band", () => {
    // 169 minutes, measured before the priority lane.
    expect(bandFor(169 * 60)).toBe("stale");
  });
});

describe("ageLabel", () => {
  it("reads as a complete phrase at every scale", () => {
    expect(ageLabel(2)).toBe("just now");
    expect(ageLabel(12)).toBe("12 sec ago");
    expect(ageLabel(120)).toBe("2 min ago");
    expect(ageLabel(7_200)).toBe("2 h ago");
    expect(ageLabel(172_800)).toBe("2 d ago");
  });

  it("never produces a phrase a caller can break by decorating it", () => {
    // "just now ago" is the bug this shape exists to prevent.
    expect(ageLabel(1)).not.toContain("ago");
  });
});

describe("freshnessOf", () => {
  it("labels a recent reading with its age, never with 'live'", () => {
    const result = freshnessOf(at(12), NOW);
    expect(result.label).toBe("Updated 12 sec ago");
    expect(result.label.toLowerCase()).not.toContain("live");
    expect(result.band).toBe("fresh");
  });

  it("distinguishes an unpriced token from a stale one", () => {
    // Nothing has gone stale if nothing was ever observed.
    const missing = freshnessOf(null, NOW);
    expect(missing.band).toBe("unknown");
    expect(missing.ageSeconds).toBeNull();
    expect(missing.label).toBe("No market data");

    expect(freshnessOf(at(9_000), NOW).band).toBe("stale");
  });

  it("treats an unreadable timestamp as absent rather than as now", () => {
    expect(freshnessOf("not-a-date", NOW).band).toBe("unknown");
  });

  it("never reports a negative age", () => {
    // A reading fractionally ahead of the browser clock is a clock
    // disagreement, not a price from the future.
    const ahead = freshnessOf(new Date(NOW + 5_000).toISOString(), NOW);
    expect(ahead.ageSeconds).toBe(0);
    expect(ahead.band).toBe("fresh");
  });

  it("carries a spelled-out description for screen readers", () => {
    expect(freshnessOf(at(120), NOW).description).toContain("2 min ago");
  });
});

describe("newestOf", () => {
  it("reports the freshest reading, not the average", () => {
    // The badge answers "is the platform still receiving data?", which one
    // recent reading settles.
    const result = newestOf([at(9_000), at(8), at(400)], NOW);
    expect(result.ageSeconds).toBe(8);
    expect(result.band).toBe("fresh");
  });

  it("is unknown when nothing has been observed at all", () => {
    expect(newestOf([], NOW).band).toBe("unknown");
    expect(newestOf([null, undefined], NOW).band).toBe("unknown");
  });

  it("ignores unreadable timestamps rather than treating them as now", () => {
    expect(newestOf(["nonsense", at(60)], NOW).ageSeconds).toBe(60);
  });
});

describe("shortMint", () => {
  it("makes a symbol collision resolvable", () => {
    // Nine distinct mints are named TNOS; the symbol alone cannot identify one.
    expect(shortMint("dDqcg6kAfrJ39D3uKDRaRaAugbZav5efevKPCnmpump")).toBe(
      "dDqc…pump",
    );
  });

  it("leaves a short identifier alone rather than mangling it", () => {
    expect(shortMint("abc")).toBe("abc");
  });

  it("invents no numbering", () => {
    // "TNOS #3" would imply an ordering the chain does not have.
    expect(shortMint("dDqcg6kAfrJ39D3uKDRaRaAugbZav5efevKPCnmpump")).not.toMatch(
      /#\d/,
    );
  });
});

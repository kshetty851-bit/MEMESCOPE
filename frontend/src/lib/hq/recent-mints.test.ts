import { describe, expect, it } from "vitest";

import { createRecentMintTracker, RECENT_MINT_WINDOW_MS } from "@/lib/hq/recent-mints";
import type { LiveEvent } from "@/hooks/use-live-updates";

const T = Date.parse("2026-06-01T00:00:00Z");

describe("the recent-mint tracker", () => {
  it("remembers mints from both event shapes the stream actually sends", () => {
    const tracker = createRecentMintTracker();
    tracker.observe({ type: "market.changed", mints: ["a", "b"] } satisfies LiveEvent, T);
    tracker.observe({ type: "score.changed", data: { mint_address: "c" } } satisfies LiveEvent, T);
    expect(tracker.snapshot(T)).toEqual(expect.arrayContaining(["a", "b", "c"]));
  });

  it("forgets a mint once it ages out of the window", () => {
    const tracker = createRecentMintTracker();
    tracker.observe({ type: "market.changed", mints: ["a"] } satisfies LiveEvent, T);
    expect(tracker.snapshot(T + 1_000)).toContain("a");
    expect(tracker.snapshot(T + RECENT_MINT_WINDOW_MS + 1)).not.toContain("a");
  });

  it("ignores an event that names no mint", () => {
    const tracker = createRecentMintTracker();
    tracker.observe({ type: "radar.changed" } satisfies LiveEvent, T);
    expect(tracker.snapshot(T)).toEqual([]);
  });

  it("bounds memory under a storm rather than growing without limit", () => {
    const tracker = createRecentMintTracker();
    for (let i = 0; i < 500; i += 1) {
      tracker.observe({ type: "market.changed", mints: [`mint-${i}`] } satisfies LiveEvent, T + i);
    }
    expect(tracker.snapshot(T + 500).length).toBeLessThanOrEqual(40);
  });

  it("orders most recently touched first", () => {
    const tracker = createRecentMintTracker();
    tracker.observe({ type: "market.changed", mints: ["old"] } satisfies LiveEvent, T);
    tracker.observe({ type: "market.changed", mints: ["new"] } satisfies LiveEvent, T + 500);
    expect(tracker.snapshot(T + 500)[0]).toBe("new");
  });
});

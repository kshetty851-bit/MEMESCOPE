import { describe, expect, it } from "vitest";

import { offPeakPercent, scopeToWindow, summarise } from "@/lib/scoreboard";
import type { RadarEntry } from "@/types/radar";

const NOW = new Date("2026-07-29T12:00:00Z").getTime();

function entry(over: Partial<RadarEntry> = {}): RadarEntry {
  return {
    mint_address: "mint",
    name: "Probe",
    symbol: "PRB",
    category: "breakout",
    original_category: "breakout",
    opportunity_score: "70",
    confidence: "80",
    first_detected_at: "2026-07-29T11:00:00Z",
    first_price: "0.001",
    first_market_cap: "100000",
    first_liquidity: "20000",
    first_opportunity_score: "70",
    current_price: "0.001",
    current_market_cap: "100000",
    current_liquidity: "20000",
    current_multiple: "1.00",
    peak_multiple: "1.00",
    peak_price: "0.001",
    peak_at: "2026-07-29T11:00:00Z",
    days_since_detection: "0.04",
    is_active: true,
    detection_reason: [],
    model_version: "radar-v1",
    last_evaluated_at: "2026-07-29T11:30:00Z",
    ...over,
  } as RadarEntry;
}

describe("radar scoreboard", () => {
  it("reads a real API-shaped page", () => {
    // Guards the wiring the browser could not confirm: string decimals in,
    // numbers out.
    const stats = summarise([
      entry({ peak_multiple: "2.634862", current_multiple: "2.634862" }),
      entry({ peak_multiple: "1.876268", current_multiple: "1.876268" }),
      entry({ peak_multiple: "1.031266", current_multiple: "1.031266" }),
    ]);

    expect(stats.total).toBe(3);
    expect(stats.bestPeak).toBeCloseTo(2.634862);
    expect(stats.reached2x).toBe(1);
  });

  it("computes the win rate over every detection, not the survivors", () => {
    // One winner, three failures. A win rate that quietly dropped the
    // failures would read 100%.
    const stats = summarise([
      entry({ peak_multiple: "5.0", current_multiple: "0.08" }),
      entry({ peak_multiple: "0.9", current_multiple: "0.4" }),
      entry({ peak_multiple: "1.1", current_multiple: "0.7" }),
      entry({ peak_multiple: "1.0", current_multiple: "0.02" }),
    ]);

    expect(stats.total).toBe(4);
    expect(stats.reached2x).toBe(1);
    expect(stats.winRate).toBe(25);
    expect(stats.greenNow).toBe(0);
  });

  it("reports a median below entry when the typical call is down", () => {
    const stats = summarise([
      entry({ current_multiple: "0.5" }),
      entry({ current_multiple: "0.9" }),
      entry({ current_multiple: "3.0" }),
    ]);
    expect(stats.medianCurrent).toBeCloseTo(0.9);
  });

  it("returns nulls rather than zeros for an empty set", () => {
    // A zero would read as "measured and found to be nothing"; null is
    // rendered as an em dash, which is the truthful "nothing to measure".
    const stats = summarise([]);
    expect(stats.bestPeak).toBeNull();
    expect(stats.medianCurrent).toBeNull();
    expect(stats.winRate).toBe(0);
  });

  it("scopes by detection date, keeping older failures out of newer windows", () => {
    const entries = [
      entry({ first_detected_at: "2026-07-29T11:00:00Z" }),
      entry({ first_detected_at: "2026-07-20T11:00:00Z" }),
      entry({ first_detected_at: "2026-06-01T11:00:00Z" }),
    ];

    expect(scopeToWindow(entries, "24h", NOW)).toHaveLength(1);
    expect(scopeToWindow(entries, "30d", NOW)).toHaveLength(2);
    expect(scopeToWindow(entries, "all", NOW)).toHaveLength(3);
  });

  it("spells out the drawdown from peak", () => {
    // The number that separates a 5x call from a 5x call that round-tripped.
    expect(offPeakPercent(5.84, 0.08)).toBe(99);
    expect(offPeakPercent(2.0, 2.0)).toBe(0);
    expect(offPeakPercent(0, 1)).toBe(0);
  });
});

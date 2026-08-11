import { describe, expect, it } from "vitest";

import {
  DEFAULT_FILTERS,
  buySellPressure,
  isServerSort,
  matchesFilters,
  scannerSortValue,
  withRank,
  type RankedEntry,
  type ScannerFilters,
} from "@/lib/scanner";
import type { RadarEntry } from "@/types/radar";

function entry(overrides: Partial<RadarEntry> = {}): RadarEntry {
  return {
    mint_address: "So11111111111111111111111111111111111111112",
    name: "Test Token",
    symbol: "TEST",
    image_url: null,
    category: "early_momentum",
    original_category: "early_momentum",
    opportunity_score: "71.4",
    confidence: "60",
    first_detected_at: "2026-08-01T00:00:00Z",
    first_price: "0.001",
    first_market_cap: "10000",
    first_liquidity: "5000",
    first_opportunity_score: "70",
    current_price: "0.002",
    current_market_cap: "20000",
    current_liquidity: "8000",
    current_multiple: "2.0",
    peak_multiple: "3.5",
    peak_price: "0.0035",
    peak_market_cap: "35000",
    peak_at: "2026-08-05T00:00:00Z",
    days_since_detection: "4",
    is_active: true,
    detection_reason: [],
    achieved_tiers: ["2x"],
    liveness: "alive",
    model_version: "v1",
    last_evaluated_at: "2026-08-09T00:00:00Z",
    base_rate: null,
    market: {
      price_usd: "0.002",
      market_cap: "20000",
      liquidity_usd: "8000",
      volume_24h: "12000",
      change_24h_pct: "14.2",
      captured_at: "2026-08-10T00:00:00Z",
      dex_name: "Raydium",
    },
    age_seconds: 7_200,
    risk_score: "62",
    risk_band: "medium",
    risk_reasons: [],
    evidence: "58",
    signal: null,
    why_now: null,
    ...overrides,
  };
}

const ranked = (overrides: Partial<RadarEntry> = {}): RankedEntry =>
  withRank([entry(overrides)])[0]!;

const filters = (overrides: Partial<ScannerFilters> = {}): ScannerFilters => ({
  ...DEFAULT_FILTERS,
  ...overrides,
});

describe("withRank", () => {
  it("stamps the server order onto the rows", () => {
    const rows = withRank([
      entry({ mint_address: "a" }),
      entry({ mint_address: "b" }),
      entry({ mint_address: "c" }),
    ]);
    expect(rows.map((row) => row.rank)).toEqual([1, 2, 3]);
  });

  it("keeps rank fixed so a client sort cannot renumber the backend ranking", () => {
    const rows = withRank([entry({ mint_address: "a" }), entry({ mint_address: "b" })]);
    const reordered = [...rows].reverse();
    // The ranking is the product's opinion. Re-sorting the view must not
    // rewrite it into a description of the sort the reader just chose.
    expect(reordered.map((row) => row.rank)).toEqual([2, 1]);
  });
});

describe("scannerSortValue", () => {
  it("reads each column from the entry", () => {
    const row = ranked();
    expect(scannerSortValue(row, "rank")).toBe(1);
    expect(scannerSortValue(row, "price")).toBe(0.002);
    expect(scannerSortValue(row, "marketCap")).toBe(20000);
    expect(scannerSortValue(row, "liquidity")).toBe(8000);
    expect(scannerSortValue(row, "volume")).toBe(12000);
    expect(scannerSortValue(row, "change")).toBe(14.2);
    expect(scannerSortValue(row, "score")).toBe(71.4);
    expect(scannerSortValue(row, "age")).toBe(7200);
    expect(scannerSortValue(row, "current")).toBe(2);
    expect(scannerSortValue(row, "peak")).toBe(3.5);
    expect(scannerSortValue(row, "evidence")).toBe(58);
  });

  it("returns null for every unmeasured value rather than zero", () => {
    const row = ranked({
      market: null,
      age_seconds: null,
      evidence: null,
      current_multiple: null,
      peak_multiple: null,
    });
    for (const key of ["price", "marketCap", "liquidity", "volume", "change", "age", "evidence", "current", "peak"]) {
      expect(scannerSortValue(row, key)).toBeNull();
    }
  });

  it("sorts risk by band order, not by the raw risk score", () => {
    // The raw score runs the opposite way — a LOW number is the dangerous end —
    // so sorting on it would silently invert the column.
    expect(scannerSortValue(ranked({ risk_band: "low" }), "risk")).toBe(0);
    expect(scannerSortValue(ranked({ risk_band: "extreme" }), "risk")).toBe(3);
    expect(
      Number(scannerSortValue(ranked({ risk_band: "low" }), "risk")),
    ).toBeLessThan(Number(scannerSortValue(ranked({ risk_band: "high" }), "risk")));
  });

  it("returns null for an unassessed risk rather than the worst band", () => {
    expect(scannerSortValue(ranked({ risk_band: null }), "risk")).toBeNull();
  });
});

describe("matchesFilters", () => {
  it("keeps everything by default", () => {
    expect(matchesFilters(ranked(), DEFAULT_FILTERS)).toBe(true);
  });

  it("filters by risk band", () => {
    expect(matchesFilters(ranked({ risk_band: "low" }), filters({ risk: "low" }))).toBe(true);
    expect(matchesFilters(ranked({ risk_band: "high" }), filters({ risk: "low" }))).toBe(false);
  });

  it("never counts an unassessed risk as safe", () => {
    // The most dangerous possible default in this product.
    expect(matchesFilters(ranked({ risk_band: null }), filters({ risk: "low" }))).toBe(false);
  });

  it("filters by age and excludes tokens of unknown age", () => {
    expect(matchesFilters(ranked({ age_seconds: 600 }), filters({ age: "1h" }))).toBe(true);
    expect(matchesFilters(ranked({ age_seconds: 7200 }), filters({ age: "1h" }))).toBe(false);
    expect(matchesFilters(ranked({ age_seconds: null }), filters({ age: "1h" }))).toBe(false);
  });

  it("filters by liquidity floor and excludes unpriced tokens", () => {
    expect(matchesFilters(ranked(), filters({ minLiquidity: 1000 }))).toBe(true);
    expect(matchesFilters(ranked(), filters({ minLiquidity: 50000 }))).toBe(false);
    // No liquidity reading is not a liquidity of zero, but it cannot satisfy a
    // floor either.
    expect(matchesFilters(ranked({ market: null }), filters({ minLiquidity: 1000 }))).toBe(false);
  });

  it("separates priced from unpriced tokens", () => {
    expect(matchesFilters(ranked(), filters({ freshness: "priced" }))).toBe(true);
    expect(matchesFilters(ranked({ market: null }), filters({ freshness: "priced" }))).toBe(false);
    expect(matchesFilters(ranked({ market: null }), filters({ freshness: "unpriced" }))).toBe(true);
  });

  it("searches symbol, name and mint case-insensitively", () => {
    expect(matchesFilters(ranked(), filters({ query: "test" }))).toBe(true);
    // Matches the name regardless of the case either side is typed in.
    expect(matchesFilters(ranked(), filters({ query: "TEST TOKEN" }))).toBe(true);
    expect(matchesFilters(ranked(), filters({ query: "tEsT tOkEn" }))).toBe(true);
    expect(matchesFilters(ranked(), filters({ query: "So1111" }))).toBe(true);
    expect(matchesFilters(ranked(), filters({ query: "nothing" }))).toBe(false);
  });

  it("ignores surrounding whitespace in the query", () => {
    expect(matchesFilters(ranked(), filters({ query: "   " }))).toBe(true);
    expect(matchesFilters(ranked(), filters({ query: "  test  " }))).toBe(true);
  });
});

describe("buySellPressure", () => {
  it("splits transaction counts", () => {
    expect(buySellPressure(68, 32)).toEqual({
      buys: 68,
      sells: 32,
      total: 100,
      buyPct: 68,
    });
  });

  it("returns null when either count is missing", () => {
    expect(buySellPressure(null, 32)).toBeNull();
    expect(buySellPressure(68, null)).toBeNull();
    expect(buySellPressure(undefined, undefined)).toBeNull();
  });

  it("returns null when there were no transactions at all", () => {
    // 0/0 is not 50% buy. Dividing here would render a balanced bar for a
    // token nobody traded.
    expect(buySellPressure(0, 0)).toBeNull();
  });

  it("handles one-sided activity without dividing by zero", () => {
    expect(buySellPressure(5, 0)?.buyPct).toBe(100);
    expect(buySellPressure(0, 5)?.buyPct).toBe(0);
  });

  it("rejects nonsense counts rather than rendering them", () => {
    expect(buySellPressure(-1, 5)).toBeNull();
    expect(buySellPressure(Number.NaN, 5)).toBeNull();
  });
});

describe("isServerSort", () => {
  it("knows exactly what /radar accepts", () => {
    for (const key of ["score", "detected", "peak", "current"]) {
      expect(isServerSort(key)).toBe(true);
    }
    for (const key of ["rank", "liquidity", "risk", "volume"]) {
      expect(isServerSort(key)).toBe(false);
    }
  });
});

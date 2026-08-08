import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CATEGORY_LABEL,
  CATEGORY_TONE,
  fetchAllRadarDetections,
  formatAgo,
  formatDays,
  formatMultiple,
  multipleTone,
} from "@/lib/radar";
import type { RadarEntry, RadarPage } from "@/types/radar";

function entry(mint: string): RadarEntry {
  return {
    mint_address: mint,
    name: `Token ${mint}`,
    symbol: "TKN",
    category: "early_momentum",
    original_category: "early_momentum",
    opportunity_score: "60",
    confidence: "60",
    first_detected_at: "2026-08-08T12:00:00Z",
    first_price: "1",
    first_market_cap: "100000",
    first_liquidity: "10000",
    first_opportunity_score: "60",
    current_price: "1",
    current_market_cap: "100000",
    current_liquidity: "10000",
    current_multiple: "1",
    peak_multiple: "1",
    peak_price: "1",
    peak_market_cap: "100000",
    peak_at: "2026-08-08T12:00:00Z",
    days_since_detection: "0",
    is_active: true,
    detection_reason: [],
    achieved_tiers: [],
    liveness: "alive",
    model_version: "radar-v1",
    last_evaluated_at: "2026-08-08T12:00:00Z",
    base_rate: null,
    market: null,
    age_seconds: null,
    risk_score: null,
    risk_band: null,
    risk_reasons: [],
    evidence: null,
    signal: null,
    why_now: null,
  };
}

function page(items: RadarEntry[], total: number, pageNumber: number): RadarPage {
  return {
    items,
    total,
    page: pageNumber,
    page_size: 100,
    applied_filters: {},
  };
}

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("fetchAllRadarDetections", () => {
  it("stitches every bounded Radar page into the permanent record", async () => {
    const first = Array.from({ length: 100 }, (_, index) => entry(`Mint${index}`));
    const second = Array.from({ length: 5 }, (_, index) => entry(`Mint${index + 100}`));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(page(first, 105, 1)))
      .mockResolvedValueOnce(response(page(second, 105, 2)));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAllRadarDetections({
      includeInactive: true,
      sort: "detected",
    });

    expect(result.items).toHaveLength(105);
    expect(result.items.at(-1)?.mint_address).toBe("Mint104");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0]![0])).toContain("page=1");
    expect(String(fetchMock.mock.calls[0]![0])).toContain("page_size=100");
    expect(String(fetchMock.mock.calls[1]![0])).toContain("page=2");
  });
});

describe("formatMultiple", () => {
  it("renders a gain as a multiple", () => {
    expect(formatMultiple("2.5")).toBe("2.50×");
  });

  it("drops the decimals once the number is large enough not to need them", () => {
    expect(formatMultiple("120.4")).toBe("120×");
  });

  it("renders a loss rather than hiding it", () => {
    // The track record is only evidence if it reports both directions.
    expect(formatMultiple("0.25")).toBe("0.25×");
  });

  it("shows an em dash where there is nothing to report", () => {
    // A missing multiple must not render as 0×, which would read as a total
    // loss rather than an absent measurement.
    expect(formatMultiple(null)).toBe("—");
    expect(formatMultiple(undefined)).toBe("—");
    expect(formatMultiple("")).toBe("—");
    expect(formatMultiple("0")).toBe("—");
  });
});

describe("multipleTone", () => {
  it("distinguishes gain, loss and no reading", () => {
    expect(multipleTone("3")).toBe("positive");
    expect(multipleTone("0.4")).toBe("negative");
    expect(multipleTone("1")).toBe("neutral");
    expect(multipleTone(null)).toBe("neutral");
  });
});

describe("formatDays", () => {
  it("reads naturally at the short end", () => {
    expect(formatDays("0.2")).toBe("today");
    expect(formatDays("1.4")).toBe("1 day");
    expect(formatDays("9.8")).toBe("9 days");
  });

  it("has no reading without a value", () => {
    expect(formatDays(null)).toBe("—");
  });
});

describe("category presentation", () => {
  it("labels every category", () => {
    for (const id of [
      "early_momentum",
      "breakout",
      "strong_community",
      "undervalued",
      "elite",
    ] as const) {
      expect(CATEGORY_LABEL[id]).toBeTruthy();
      expect(CATEGORY_TONE[id]).toMatch(/^var\(--color-/);
    }
  });

  it("reserves gold for Elite alone", () => {
    // §10: gold is the scarcest thing in the palette and marks the rarest
    // verdict. Spending it on a common category would devalue the one thing
    // meant to feel rare.
    expect(CATEGORY_TONE.elite).toBe("var(--color-apex)");

    const others = (
      ["early_momentum", "breakout", "strong_community", "undervalued"] as const
    ).map((id) => CATEGORY_TONE[id]);
    expect(others).not.toContain("var(--color-apex)");
  });
});

describe("formatAgo", () => {
  it("does not produce 'today ago'", () => {
    // The bug this function exists to prevent: callers appending " ago" to
    // formatDays produced "today ago" wherever a detection was fresh.
    expect(formatAgo("0.3")).toBe("today");
  });

  it("reads as an elapsed duration otherwise", () => {
    expect(formatAgo("1.2")).toBe("1 day ago");
    expect(formatAgo("14")).toBe("14 days ago");
  });

  it("has no reading without a value", () => {
    expect(formatAgo(null)).toBe("—");
  });
});

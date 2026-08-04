import { describe, expect, it } from "vitest";

import {
  baseRateSummary,
  changeTone,
  compactAge,
  compactUsd,
  evidenceDots,
  expiresIn,
  riskLabel,
  signedPct,
  sortRadarEntries,
  tokenNaming,
} from "@/lib/radar-row";
import type { BaseRate, RadarEntry } from "@/types/radar";

/**
 * Radar row presentation.
 *
 * Almost every assertion here is about *absence*, because that is where a
 * ranking product is tempted to lie. A missing price rendered as $0, a missing
 * risk rendered as 0, or a thin sample rendered as a percentage would each be
 * an estimate the platform does not make.
 */

function entry(overrides: Partial<RadarEntry>): RadarEntry {
  return {
    mint_address: "probe",
    name: null,
    symbol: null,
    category: "early_momentum",
    original_category: "early_momentum",
    opportunity_score: "70",
    confidence: "40",
    first_detected_at: "2026-08-01T00:00:00Z",
    first_price: null,
    first_market_cap: null,
    first_liquidity: null,
    first_opportunity_score: "70",
    current_price: null,
    current_market_cap: null,
    current_liquidity: null,
    current_multiple: "1.0",
    peak_multiple: "1.0",
    peak_price: null,
    peak_market_cap: null,
    peak_at: null,
    days_since_detection: "2",
    is_active: true,
    detection_reason: [],
    achieved_tiers: [],
    liveness: "alive",
    model_version: "v1",
    last_evaluated_at: "2026-08-04T00:00:00Z",
    base_rate: null,
    market: null,
    age_seconds: null,
    risk_score: null,
    risk_band: null,
    risk_reasons: [],
    evidence: null,
    signal: null,
    why_now: null,
    ...overrides,
  };
}

function rate(overrides: Partial<BaseRate>): BaseRate {
  return {
    category: "early_momentum",
    sample: 41,
    reached_2x: 13,
    reached_5x: 3,
    reached_10x: 0,
    reached_100x: 0,
    median_peak_multiple: "1.76",
    median_current_multiple: "0.07",
    sufficient: true,
    insufficient_reason: null,
    minimum_sample: 10,
    ...overrides,
  };
}

describe("compactUsd", () => {
  it("returns null for absent money so callers render their own dash", () => {
    expect(compactUsd(null)).toBeNull();
    expect(compactUsd(undefined)).toBeNull();
    expect(compactUsd("")).toBeNull();
  });

  it("distinguishes a real zero from an absent figure", () => {
    // A token priced at zero and a token nobody priced are different facts.
    expect(compactUsd("0")).toBe("$0.0000");
    expect(compactUsd(null)).toBeNull();
  });

  it("compacts by magnitude", () => {
    expect(compactUsd("2500000000")).toBe("$2.50B");
    expect(compactUsd("3409378")).toBe("$3.41M");
    expect(compactUsd("18000")).toBe("$18.0K");
  });
});

describe("signedPct", () => {
  it("returns null rather than a flat 0% when nothing was measured", () => {
    // "Unchanged" and "we were not watching yet" are different claims.
    expect(signedPct(null)).toBeNull();
  });

  it("signs a gain and leaves a loss its own sign", () => {
    expect(signedPct("12.5")).toBe("+12.5%");
    expect(signedPct("-40.2")).toBe("-40.2%");
  });

  it("treats an unmeasured change as neutral, not as flat", () => {
    expect(changeTone(null)).toBe("neutral");
    expect(changeTone("0")).toBe("neutral");
    expect(changeTone("1")).toBe("positive");
    expect(changeTone("-1")).toBe("negative");
  });
});

describe("compactAge", () => {
  it("returns null for an unknown age rather than claiming zero seconds", () => {
    expect(compactAge(null)).toBeNull();
    expect(compactAge(undefined)).toBeNull();
  });

  it("scales the unit to the magnitude", () => {
    expect(compactAge(45)).toBe("45s");
    expect(compactAge(720)).toBe("12m");
    expect(compactAge(10_800)).toBe("3h");
    expect(compactAge(432_000)).toBe("5d");
  });

  it("never renders a negative age", () => {
    expect(compactAge(-5)).toBe("0s");
  });
});

describe("expiresIn", () => {
  it("says a lapsed claim has expired rather than showing 0s", () => {
    expect(expiresIn(0)).toBe("expired");
    expect(expiresIn(-10)).toBe("expired");
  });

  it("is absent when there is no signal to expire", () => {
    expect(expiresIn(null)).toBeNull();
  });
});

describe("riskLabel", () => {
  it("returns nothing for an unassessed risk", () => {
    // On this model a score of 0 reads as maximum danger, so inventing a band
    // for a dimension with no source would be the most consequential lie here.
    expect(riskLabel(null)).toBeNull();
    expect(riskLabel(undefined)).toBeNull();
  });

  it("names each band the server cut", () => {
    expect(riskLabel("low")).toEqual({ label: "Low", tone: "safe" });
    expect(riskLabel("medium")).toEqual({ label: "Medium", tone: "warn" });
    expect(riskLabel("high")).toEqual({ label: "High", tone: "danger" });
    expect(riskLabel("extreme")).toEqual({ label: "Extreme", tone: "danger" });
  });

  it("renders an unknown band as unmeasured rather than as its raw code", () => {
    expect(riskLabel("catastrophic")).toBeNull();
  });
});

describe("evidenceDots", () => {
  it("is absent when the row was never scored", () => {
    // Distinct from zero dots, which is the measured claim that the model had
    // data for none of its weight.
    expect(evidenceDots(null)).toBeNull();
    expect(evidenceDots("0")).toBe(0);
  });

  it("fills by quartile", () => {
    expect(evidenceDots("10")).toBe(1);
    expect(evidenceDots("40")).toBe(2);
    expect(evidenceDots("62")).toBe(3);
    expect(evidenceDots("85")).toBe(4);
    expect(evidenceDots("100")).toBe(4);
  });
});

describe("baseRateSummary", () => {
  it("is absent when no rate was published", () => {
    expect(baseRateSummary(null)).toBeNull();
  });

  it("quotes shares of the sample, never a claim about this token", () => {
    const summary = baseRateSummary(rate({}));
    expect(summary?.quotable).toBe(true);
    expect(summary?.headline).toBe("41 similar signals");
    expect(summary?.lines).toContain("32% reached 2×");
  });

  it("refuses to quote a percentage from a thin sample", () => {
    // A rate from n=3 is noise wearing the costume of evidence. The backend
    // publishes the threshold and the reason; the client prints the reason.
    const summary = baseRateSummary(
      rate({
        sample: 3,
        sufficient: false,
        insufficient_reason: "Too few observations.",
      }),
    );
    expect(summary?.quotable).toBe(false);
    expect(summary?.lines).toEqual(["Too few observations."]);
    expect(summary?.lines.join(" ")).not.toContain("%");
  });

  it("falls back to naming the published minimum when no reason was sent", () => {
    const summary = baseRateSummary(
      rate({ sample: 2, sufficient: false, insufficient_reason: null }),
    );
    expect(summary?.lines[0]).toContain("10");
  });
});

describe("tokenNaming", () => {
  it("prefers the symbol and keeps the name beside it", () => {
    const naming = tokenNaming(entry({ symbol: "TBB", name: "The Bitcoin Bull" }));
    expect(naming).toEqual({ primary: "TBB", secondary: "The Bitcoin Bull" });
  });

  it("drops a name that only repeats the symbol", () => {
    // "SAOF SAOF" reads as two facts and is one.
    expect(tokenNaming(entry({ symbol: "SAOF", name: "SAOF" })).secondary).toBeNull();
    expect(tokenNaming(entry({ symbol: "TikTok", name: "tiktok" })).secondary).toBeNull();
  });

  it("falls back to the mint rather than the word Unnamed", () => {
    // An unidentified token is a real state, and the mint is the one identifier
    // that always exists — and the only one a reader can act on.
    const naming = tokenNaming(
      entry({ mint_address: "Gymbmn9wwMKe4NnmVceyyfpncp9arbwPfSdBsyY9pump", symbol: null, name: null }),
    );
    expect(naming.primary).toBe("Gymb…pump");
    expect(naming.secondary).toBeNull();
  });

  it("treats a blank symbol as absent rather than as a name", () => {
    expect(tokenNaming(entry({ symbol: "  ", name: "Real Name" })).primary).toBe(
      "Real Name",
    );
  });
});

describe("sortRadarEntries", () => {
  const a = entry({ mint_address: "a", opportunity_score: "70", peak_multiple: "9", age_seconds: 900 });
  const b = entry({ mint_address: "b", opportunity_score: "90", peak_multiple: "2", age_seconds: 100 });
  const c = entry({ mint_address: "c", opportunity_score: "80", peak_multiple: "5", age_seconds: 500 });
  const rows = [a, b, c];

  it("does not mutate the page it was given", () => {
    const before = rows.map((row) => row.mint_address);
    sortRadarEntries(rows, "peak");
    expect(rows.map((row) => row.mint_address)).toEqual(before);
  });

  it("orders by each key", () => {
    expect(sortRadarEntries(rows, "score").map((r) => r.mint_address)).toEqual(["b", "c", "a"]);
    expect(sortRadarEntries(rows, "peak").map((r) => r.mint_address)).toEqual(["a", "c", "b"]);
    expect(sortRadarEntries(rows, "age").map((r) => r.mint_address)).toEqual(["b", "c", "a"]);
  });

  it("sinks unmeasured values rather than ranking them as zero", () => {
    const withGap = [entry({ mint_address: "x", peak_multiple: null }), a];
    expect(sortRadarEntries(withGap, "peak").map((r) => r.mint_address)).toEqual(["a", "x"]);
  });

  it("sorts a token of unknown age last, not first", () => {
    const withGap = [entry({ mint_address: "x", age_seconds: null }), b];
    expect(sortRadarEntries(withGap, "age").map((r) => r.mint_address)).toEqual(["b", "x"]);
  });
});

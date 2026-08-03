import { describe, expect, it } from "vitest";

import {
  NO_FILTERS,
  applyFilters,
  formatAgo,
  formatExpiresIn,
  hasActiveFilters,
  leadSignal,
  matchesSearch,
  secondsSince,
  signalLabel,
  signalTypesIn,
  sortOpportunities,
} from "@/lib/opportunities";
import type { Opportunity, OpportunitySignal } from "@/types/opportunity";

function signal(overrides: Partial<OpportunitySignal> = {}): OpportunitySignal {
  return {
    signal_type: "fresh_graduation",
    provider: "fresh_graduation",
    status: "active",
    severity: "major",
    strength: "100.00",
    confidence: "55.00",
    confirmations: 2,
    observations: 6,
    detected_at: "2026-08-02T12:00:00Z",
    last_confirmed_at: "2026-08-02T12:05:00Z",
    expires_at: "2026-08-04T12:00:00Z",
    expires_in_seconds: 172_800,
    reason_codes: ["graduated_from_bonding_curve"],
    evidence: [],
    explanation: {
      headline: "Freshly graduated",
      trigger: "This token has left its bonding curve.",
      boundary: null,
      delta: [],
      corroboration: [],
      limits: ["Liquidity could not be verified before graduation."],
    },
    ...overrides,
  };
}

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    mint_address: "MintAAA",
    name: "Test Token",
    symbol: "TEST",
    generation: 1,
    status: "active",
    stage: "fresh_graduation",
    priority: "60.00",
    priority_band: "high",
    confidence: "55.00",
    detected_at: "2026-08-02T12:00:00Z",
    last_confirmed_at: "2026-08-02T12:05:00Z",
    confirmed_age_seconds: 300,
    signals: [signal()],
    ...overrides,
  };
}

describe("formatExpiresIn", () => {
  it("reports coarse buckets rather than a countdown", () => {
    // A countdown to the second would imply the expiry moment matters to the
    // reader. What matters is roughly how long the claim still stands.
    expect(formatExpiresIn(90)).toBe("2m");
    expect(formatExpiresIn(7200)).toBe("2h");
    expect(formatExpiresIn(259_200)).toBe("3d");
  });

  it("says expired rather than showing a negative", () => {
    expect(formatExpiresIn(0)).toBe("Expired");
    expect(formatExpiresIn(-500)).toBe("Expired");
  });

  it("never rounds a live signal down to zero minutes", () => {
    expect(formatExpiresIn(20)).toBe("1m");
  });
});

describe("formatAgo", () => {
  it("reads as elapsed time", () => {
    expect(formatAgo(10)).toBe("just now");
    expect(formatAgo(300)).toBe("5m ago");
    expect(formatAgo(7200)).toBe("2h ago");
    expect(formatAgo(172_800)).toBe("2d ago");
  });
});

describe("secondsSince", () => {
  it("measures elapsed seconds", () => {
    const now = Date.parse("2026-08-02T12:10:00Z");
    expect(secondsSince("2026-08-02T12:00:00Z", now)).toBe(600);
  });

  it("floors a future timestamp at zero", () => {
    // Container clock skew must not render as impossibly fresh, or worse as a
    // negative age. Same guard the backend's health service applies.
    const now = Date.parse("2026-08-02T12:00:00Z");
    expect(secondsSince("2026-08-02T12:05:00Z", now)).toBe(0);
  });

  it("does not throw on an unparseable timestamp", () => {
    expect(secondsSince("not a date")).toBe(0);
  });
});

describe("signalLabel", () => {
  it("labels the types this build knows", () => {
    expect(signalLabel("fresh_graduation")).toBe("Fresh graduation");
    expect(signalLabel("pre_breakout")).toBe("Pre-breakout");
  });

  it("derives a readable label for a type it has never seen", () => {
    // The engine can register a provider emitting a type this build predates.
    // A badge reading "Some future signal" beats a crash or a dropped badge.
    expect(signalLabel("some_future_signal")).toBe("Some future signal");
  });
});

describe("signalTypesIn", () => {
  it("collects the distinct types present, sorted", () => {
    const types = signalTypesIn([
      opportunity({ signals: [signal(), signal({ signal_type: "breakout" })] }),
      opportunity({ mint_address: "MintB", signals: [signal()] }),
    ]);
    expect(types).toEqual(["breakout", "fresh_graduation"]);
  });

  it("returns nothing for an empty board", () => {
    expect(signalTypesIn([])).toEqual([]);
  });
});

describe("leadSignal", () => {
  it("picks the highest-confidence signal", () => {
    const item = opportunity({
      signals: [
        signal({ signal_type: "breakout", confidence: "30.00" }),
        signal({ confidence: "80.00" }),
      ],
    });
    expect(leadSignal(item)?.confidence).toBe("80.00");
  });

  it("returns null when every signal has lapsed", () => {
    expect(leadSignal(opportunity({ signals: [] }))).toBeNull();
  });
});

describe("matchesSearch", () => {
  const item = opportunity({ name: "Inward Unrest", symbol: "NWRDN" });

  it("matches on symbol, name and mint, case-insensitively", () => {
    expect(matchesSearch(item, "nwrdn")).toBe(true);
    expect(matchesSearch(item, "INWARD")).toBe(true);
    expect(matchesSearch(item, "mintaaa")).toBe(true);
  });

  it("matches a fragment from the middle of a mint", () => {
    // A pasted partial address rarely starts at character one.
    expect(matchesSearch(opportunity({ mint_address: "abc123xyz" }), "123")).toBe(true);
  });

  it("returns everything for an empty or whitespace search", () => {
    expect(matchesSearch(item, "")).toBe(true);
    expect(matchesSearch(item, "   ")).toBe(true);
  });

  it("does not match an unrelated term", () => {
    expect(matchesSearch(item, "bonk")).toBe(false);
  });

  it("does not throw when identity is absent", () => {
    const anonymous = opportunity({ name: null, symbol: null });
    expect(matchesSearch(anonymous, "test")).toBe(false);
  });
});

describe("applyFilters", () => {
  const board = [
    opportunity({ mint_address: "A", confidence: "80.00", priority_band: "critical" }),
    opportunity({
      mint_address: "B",
      stage: "near_graduation",
      confidence: "20.00",
      priority_band: "low",
      signals: [signal({ signal_type: "near_graduation" })],
    }),
  ];

  it("returns everything with no filters applied", () => {
    expect(applyFilters(board, NO_FILTERS)).toHaveLength(2);
  });

  it("filters by stage", () => {
    const result = applyFilters(board, { ...NO_FILTERS, stage: "near_graduation" });
    expect(result.map((item) => item.mint_address)).toEqual(["B"]);
  });

  it("filters by signal type present on the opportunity", () => {
    const result = applyFilters(board, { ...NO_FILTERS, signalType: "near_graduation" });
    expect(result.map((item) => item.mint_address)).toEqual(["B"]);
  });

  it("filters by minimum confidence", () => {
    const result = applyFilters(board, { ...NO_FILTERS, minConfidence: 50 });
    expect(result.map((item) => item.mint_address)).toEqual(["A"]);
  });

  it("filters by priority band, treating an empty selection as all", () => {
    expect(applyFilters(board, { ...NO_FILTERS, priorities: [] })).toHaveLength(2);
    expect(
      applyFilters(board, { ...NO_FILTERS, priorities: ["critical"] }).map(
        (item) => item.mint_address,
      ),
    ).toEqual(["A"]);
  });

  it("combines filters conjunctively", () => {
    const result = applyFilters(board, {
      ...NO_FILTERS,
      stage: "fresh_graduation",
      minConfidence: 50,
    });
    expect(result.map((item) => item.mint_address)).toEqual(["A"]);
  });

  it("never mutates the input", () => {
    const original = [...board];
    applyFilters(board, { ...NO_FILTERS, minConfidence: 90 });
    expect(board).toEqual(original);
  });
});

describe("hasActiveFilters", () => {
  it("is false for the default filter set", () => {
    expect(hasActiveFilters(NO_FILTERS)).toBe(false);
  });

  it("ignores a whitespace-only search", () => {
    // Otherwise the empty state would claim filters are hiding results when a
    // user has only pressed space.
    expect(hasActiveFilters({ ...NO_FILTERS, search: "  " })).toBe(false);
  });

  it("is true once any filter narrows the board", () => {
    expect(hasActiveFilters({ ...NO_FILTERS, stage: "established" })).toBe(true);
    expect(hasActiveFilters({ ...NO_FILTERS, minConfidence: 25 })).toBe(true);
    expect(hasActiveFilters({ ...NO_FILTERS, priorities: ["low"] })).toBe(true);
    expect(hasActiveFilters({ ...NO_FILTERS, search: "bonk" })).toBe(true);
  });
});

describe("sortOpportunities", () => {
  const board = [
    opportunity({
      mint_address: "B",
      priority: "20.00",
      confidence: "90.00",
      detected_at: "2026-08-02T10:00:00Z",
    }),
    opportunity({
      mint_address: "A",
      priority: "80.00",
      confidence: "10.00",
      detected_at: "2026-08-02T09:00:00Z",
    }),
    opportunity({
      mint_address: "C",
      priority: "50.00",
      confidence: "50.00",
      detected_at: "2026-08-02T11:00:00Z",
    }),
  ];

  it("ranks by priority, highest first", () => {
    expect(sortOpportunities(board, "priority").map((i) => i.mint_address)).toEqual([
      "A",
      "C",
      "B",
    ]);
  });

  it("ranks by confidence, highest first", () => {
    expect(sortOpportunities(board, "confidence").map((i) => i.mint_address)).toEqual([
      "B",
      "C",
      "A",
    ]);
  });

  it("ranks by newest detection first", () => {
    expect(sortOpportunities(board, "newest").map((i) => i.mint_address)).toEqual([
      "C",
      "B",
      "A",
    ]);
  });

  it("breaks ties deterministically so cards do not swap between polls", () => {
    // A partial order means a card moving for no reason the user can see, every
    // sixty seconds. The backend's own board query holds the same discipline.
    const tied = [
      opportunity({ mint_address: "Z", priority: "50.00" }),
      opportunity({ mint_address: "A", priority: "50.00" }),
      opportunity({ mint_address: "M", priority: "50.00" }),
    ];
    expect(sortOpportunities(tied, "priority").map((i) => i.mint_address)).toEqual([
      "A",
      "M",
      "Z",
    ]);
    expect(sortOpportunities(tied, "priority")).toEqual(sortOpportunities(tied, "priority"));
  });

  it("never mutates the input", () => {
    const original = board.map((item) => item.mint_address);
    sortOpportunities(board, "confidence");
    expect(board.map((item) => item.mint_address)).toEqual(original);
  });
});

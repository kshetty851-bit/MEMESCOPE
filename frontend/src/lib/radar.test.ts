import { describe, expect, it } from "vitest";

import {
  CATEGORY_LABEL,
  CATEGORY_TONE,
  formatAgo,
  formatDays,
  formatMultiple,
  multipleTone,
} from "@/lib/radar";

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

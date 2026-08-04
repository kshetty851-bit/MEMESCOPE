import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RadarRow } from "@/components/radar/radar-row";
import type { RadarEntry } from "@/types/radar";

/**
 * What a Radar row shows, and what it refuses to show.
 *
 * The rendering rules matter more than the layout: a row that prints "$0" for a
 * price nobody observed, or a risk of zero for a dimension with no source, has
 * fabricated the two figures a trader would act on hardest.
 */

function entry(overrides: Partial<RadarEntry> = {}): RadarEntry {
  return {
    mint_address: "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump",
    name: "Inward Unrest",
    symbol: "NWRDN",
    category: "early_momentum",
    original_category: "early_momentum",
    opportunity_score: "78.44",
    confidence: "55.00",
    first_detected_at: "2026-08-02T12:00:00Z",
    first_price: "0.00001",
    first_market_cap: "121582",
    first_liquidity: "24181",
    first_opportunity_score: "58.93",
    current_price: "0.00003",
    current_market_cap: "364000",
    current_liquidity: "40000",
    current_multiple: "3.0",
    peak_multiple: "5.5",
    peak_price: "0.000055",
    peak_market_cap: "660000",
    peak_at: "2026-08-03T12:00:00Z",
    days_since_detection: "2",
    is_active: true,
    detection_reason: ["volume_expanding"],
    achieved_tiers: ["2x", "5x"],
    liveness: "alive",
    model_version: "radar-v1",
    last_evaluated_at: "2026-08-04T10:00:00Z",
    base_rate: {
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
    },
    market: {
      price_usd: "0.00003",
      market_cap: "364000",
      liquidity_usd: "40000",
      volume_24h: "89000",
      change_24h_pct: "12.50",
      captured_at: "2026-08-04T10:00:00Z",
      dex_name: "pumpswap",
    },
    age_seconds: 21_600,
    risk_score: "82.00",
    risk_band: "low",
    risk_reasons: [],
    evidence: "85.00",
    signal: null,
    why_now: {
      code: "reason:resistance_broken",
      sentence: "Price has pushed above its recent high.",
    },
    ...overrides,
  };
}

afterEach(cleanup);

describe("RadarRow", () => {
  it("shows the rank, the score and both multiples", () => {
    render(<RadarRow entry={entry()} rank={3} />);

    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("78")).toBeInTheDocument();
    // Peak and current always together: a call that ran 5.5× and sits at 3× is
    // not a 5.5× call, and showing only the peak would say it was.
    expect(screen.getByText("3.00×")).toBeInTheDocument();
    expect(screen.getByText("5.50×")).toBeInTheDocument();
  });

  it("renders the market strip a trader needs to act", () => {
    render(<RadarRow entry={entry()} rank={1} />);

    expect(screen.getByText("$364.0K")).toBeInTheDocument();
    expect(screen.getByText("$40.0K")).toBeInTheDocument();
    expect(screen.getByText("$89.0K")).toBeInTheDocument();
    expect(screen.getByText("+12.5%")).toBeInTheDocument();
    expect(screen.getByText("6h")).toBeInTheDocument();
  });

  it("shows the price, which a trader cannot size a position without", () => {
    render(<RadarRow entry={entry()} rank={1} />);
    expect(screen.getByText("$0.0000")).toBeInTheDocument();
  });

  it("dashes an unpriced token rather than pricing it at zero", () => {
    render(<RadarRow entry={entry({ market: null })} rank={1} />);

    // Five market cells, all absent, all dashed — never $0.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(5);
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });

  it("says risk is unmeasured rather than banding it as safe or extreme", () => {
    render(<RadarRow entry={entry({ risk_band: null })} rank={1} />);

    expect(screen.getByText("Risk —")).toBeInTheDocument();
  });

  it("names the band the server cut", () => {
    render(<RadarRow entry={entry({ risk_band: "extreme" })} rank={1} />);
    expect(screen.getByText("Extreme risk")).toBeInTheDocument();

    cleanup();
    render(<RadarRow entry={entry({ risk_band: "low" })} rank={1} />);
    expect(screen.getByText("Low risk")).toBeInTheDocument();
  });

  it("shows evidence as dots rather than a number beside the score", () => {
    // A percentage beside a score invites the reader to multiply them.
    render(<RadarRow entry={entry({ evidence: "40" })} rank={1} />);

    expect(screen.getByLabelText("Evidence 2 of 4")).toBeInTheDocument();
    expect(screen.queryByText(/40%/)).not.toBeInTheDocument();
  });

  it("distinguishes an unscored row from one scored on nothing", () => {
    render(<RadarRow entry={entry({ evidence: null })} rank={1} />);
    expect(screen.getByLabelText("Evidence not recorded")).toBeInTheDocument();
  });

  it("quotes the base rate as history, not as a forecast", () => {
    render(<RadarRow entry={entry()} rank={1} />);

    expect(screen.getByText("Similar historical signals")).toBeInTheDocument();
    expect(screen.getByText("41 similar signals")).toBeInTheDocument();
    expect(screen.getByText("32% reached 2×")).toBeInTheDocument();
  });

  it("prints the reason instead of a rate when the sample is thin", () => {
    render(
      <RadarRow
        entry={entry({
          base_rate: {
            category: "elite",
            sample: 3,
            reached_2x: 2,
            reached_5x: 1,
            reached_10x: 0,
            reached_100x: 0,
            median_peak_multiple: null,
            median_current_multiple: null,
            sufficient: false,
            insufficient_reason: "Too few observations.",
            minimum_sample: 10,
          },
        })}
        rank={1}
      />,
    );

    expect(screen.getByText("Too few observations.")).toBeInTheDocument();
    // 2 of 3 is 67%, and printing that would be noise wearing evidence's costume.
    expect(screen.queryByText(/67%/)).not.toBeInTheDocument();
  });

  it("displays the backend's why-now sentence on every row", () => {
    render(<RadarRow entry={entry({ signal: null })} rank={1} />);

    expect(
      screen.getByText("Price has pushed above its recent high."),
    ).toBeInTheDocument();
  });

  it("names a live signal in trader language, never in the engine's", () => {
    render(
      <RadarRow
        entry={entry({
          signal: {
            signal_type: "fresh_graduation",
            label: "Recently graduated from Pump.fun",
            expires_in_seconds: 20_745,
          },
          why_now: {
            code: "signal:fresh_graduation",
            sentence: "Graduated from Pump.fun 18 minutes ago.",
          },
        })}
        rank={1}
      />,
    );

    // The sentence already names the signal and adds the timing, so the chip
    // would print one fact twice. The expiry still has to survive.
    expect(screen.getByText("Graduated from Pump.fun 18 minutes ago.")).toBeInTheDocument();
    expect(screen.queryByText("Recently graduated from Pump.fun")).not.toBeInTheDocument();
    expect(screen.getByText(/Expires in 5h/)).toBeInTheDocument();
    // The stable code is for branching, never for reading.
    expect(screen.queryByText(/fresh_graduation/)).not.toBeInTheDocument();
  });

  it("shows the signal chip when the sentence is about something else", () => {
    render(
      <RadarRow
        entry={entry({
          signal: {
            signal_type: "breakout",
            label: "Strong buying pressure",
            expires_in_seconds: 20_745,
          },
          why_now: {
            code: "move_up",
            sentence: "Trading 3.5x above where it was detected.",
          },
        })}
        rank={1}
      />,
    );

    expect(screen.getByText("Strong buying pressure")).toBeInTheDocument();
    expect(
      screen.getByText("Trading 3.5x above where it was detected."),
    ).toBeInTheDocument();
  });

  it("never puts engine vocabulary on screen", () => {
    const { container } = render(
      <RadarRow
        entry={entry({
          signal: {
            signal_type: "breakout",
            label: "Strong buying pressure",
            expires_in_seconds: 20_745,
          },
        })}
        rank={1}
      />,
    );

    const text = container.textContent ?? "";
    for (const jargon of [
      "priority",
      "provider",
      "confidence",
      "strength",
      "confirmations",
      "severity",
      "breakout",
      "_",
    ]) {
      expect(text.toLowerCase()).not.toContain(jargon);
    }
  });

  it("offers four distinct destinations, not the same one twice", () => {
    // Before this, "Chart" and "DexScreener" were the same URL wearing two icons.
    const { container } = render(<RadarRow entry={entry()} rank={1} />);

    const hrefs = Array.from(container.querySelectorAll("a[target=_blank]")).map((a) =>
      a.getAttribute("href"),
    );
    expect(new Set(hrefs).size).toBe(hrefs.length);
    expect(hrefs.some((h) => h?.includes("pump.fun"))).toBe(true);
    expect(hrefs.some((h) => h?.includes("dexscreener"))).toBe(true);
    expect(hrefs.some((h) => h?.includes("solscan"))).toBe(true);
  });

  it("marks paper trading unavailable rather than offering a button that does nothing", () => {
    render(<RadarRow entry={entry()} rank={1} />);

    const action = screen.getByText("Paper trade");
    expect(action).toHaveAttribute("aria-disabled");
    expect(action.tagName).not.toBe("BUTTON");
  });

  it("is a complete row when nothing is live", () => {
    render(<RadarRow entry={entry({ signal: null })} rank={1} />);

    expect(screen.getByText("78")).toBeInTheDocument();
    expect(screen.queryByText(/Recently graduated/)).not.toBeInTheDocument();
  });

  it("never claims a token is dead", () => {
    // Nothing in this system establishes death, so no row may imply it.
    const { container } = render(
      <RadarRow entry={entry({ liveness: "unknown" })} rank={1} />,
    );
    expect((container.textContent ?? "").toLowerCase()).not.toContain("inactive");
  });

  it("keeps the reading's own timestamp reachable", () => {
    // The "liveness" chip was internal vocabulary and went; dropping the fact
    // with it would make a stale row indistinguishable from a live one.
    render(<RadarRow entry={entry()} rank={1} />);

    expect(screen.getByTitle(/Last observed/)).toBeInTheDocument();
  });

  it("says a token was never observed rather than dating it to now", () => {
    render(<RadarRow entry={entry({ market: null })} rank={1} />);
    expect(screen.getByTitle("Never observed.")).toBeInTheDocument();
  });
});

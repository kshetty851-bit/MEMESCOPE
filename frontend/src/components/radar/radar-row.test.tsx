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
    risk_reasons: [],
    evidence: "85.00",
    signal: null,
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
    expect(screen.getByText("Age 6h")).toBeInTheDocument();
  });

  it("dashes an unpriced token rather than pricing it at zero", () => {
    render(<RadarRow entry={entry({ market: null })} rank={1} />);

    // Four market cells, all absent, all dashed — never $0.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });

  it("says risk was not assessed rather than scoring it zero", () => {
    render(<RadarRow entry={entry({ risk_score: null })} rank={1} />);

    expect(screen.getByText("Risk not assessed")).toBeInTheDocument();
  });

  it("names the risk band, reading high as safe", () => {
    render(<RadarRow entry={entry({ risk_score: "20" })} rank={1} />);
    expect(screen.getByText("High risk")).toBeInTheDocument();

    cleanup();
    render(<RadarRow entry={entry({ risk_score: "88" })} rank={1} />);
    expect(screen.getByText("Low risk")).toBeInTheDocument();
  });

  it("publishes how much of the model had data", () => {
    render(<RadarRow entry={entry({ evidence: "40" })} rank={1} />);
    expect(screen.getByText("Evidence Thin")).toBeInTheDocument();
  });

  it("quotes the base rate as history, not as a forecast", () => {
    render(<RadarRow entry={entry()} rank={1} />);

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

  it("displays the engine's own why-now line verbatim", () => {
    render(
      <RadarRow
        entry={entry({
          signal: {
            signal_type: "breakout",
            provider: "breakout",
            severity: "major",
            headline: "Breaking out",
            why_now: "The price has moved above the highest level of its own recent observations.",
            confidence: "61.53",
            expires_in_seconds: 20_745,
          },
        })}
        rank={1}
      />,
    );

    expect(screen.getByText("Breaking out")).toBeInTheDocument();
    expect(
      screen.getByText(/moved above the highest level of its own recent observations/),
    ).toBeInTheDocument();
    // A signal is a statement with a shelf life; a row that hides it invites
    // acting on a stale one.
    expect(screen.getByText("expires in 5h")).toBeInTheDocument();
  });

  it("is a complete row when nothing is live", () => {
    render(<RadarRow entry={entry({ signal: null })} rank={1} />);

    expect(screen.getByText("78")).toBeInTheDocument();
    expect(screen.queryByText(/expires in/)).not.toBeInTheDocument();
  });

  it("marks a token not seen in 24 hours as unknown rather than dead", () => {
    render(<RadarRow entry={entry({ liveness: "unknown" })} rank={1} />);

    expect(screen.getByText("Liveness unknown")).toBeInTheDocument();
    expect(screen.queryByText(/inactive/i)).not.toBeInTheDocument();
  });
});

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MarketPanel } from "@/components/token/market-panel";
import { ScoreWaterfall } from "@/components/token/score-waterfall";
import { VerdictBand } from "@/components/token/verdict-band";
import type { DiscoveredToken, MarketSnapshot, TokenMarket } from "@/types/api";
import type { RadarEntry } from "@/types/radar";
import type { ScoreComponent, TokenScore } from "@/types/score";

/**
 * The dossier is the one screen with the engine's real `ScoreGrade`, the
 * component breakdown and the transaction counts. These assert that each of
 * those is read rather than derived, and that every absence stays an absence.
 */

function component(overrides: Partial<ScoreComponent> = {}): ScoreComponent {
  return {
    id: "liquidity_depth",
    agent: "sentinel",
    available: true,
    score: "72.5",
    declared_weight: "0.25",
    effective_weight: "0.25",
    contribution: "18.13",
    raw: {},
    reasons: [],
    ...overrides,
  };
}

function tokenScore(overrides: Partial<TokenScore> = {}): TokenScore {
  return {
    mint_address: "So11111111111111111111111111111111111111112",
    score: "71.4",
    opportunity_raw: "78.2",
    grade: "strong",
    is_elite: false,
    evidence: {
      evidence: "58",
      coverage: "65",
      observations: 42,
      freshness: "0.9",
      confidence: "52",
    },
    risk: { market_risk: "38", has_veto: false, deduction: "6.8" },
    model_version: "v2.1",
    evaluated_at: "2026-08-10T00:00:00Z",
    latest_snapshot_at: "2026-08-10T00:00:00Z",
    previous_score: "68",
    last_trigger: "market",
    components: [component()],
    reasons: [],
    ...overrides,
  };
}

function radarEntry(overrides: Partial<RadarEntry> = {}): RadarEntry {
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
    peak_multiple: "4.0",
    peak_price: "0.004",
    peak_market_cap: "40000",
    peak_at: "2026-08-05T00:00:00Z",
    days_since_detection: "4",
    is_active: true,
    detection_reason: [],
    achieved_tiers: [],
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
      captured_at: new Date().toISOString(),
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

function snapshot(overrides: Partial<MarketSnapshot> = {}): MarketSnapshot {
  return {
    id: "snap-1",
    mint_address: "So11111111111111111111111111111111111111112",
    captured_at: new Date().toISOString(),
    price_usd: "0.002",
    price_native: "0.0000123",
    liquidity_usd: "8000",
    fully_diluted_valuation: "25000",
    market_cap: "20000",
    volume_24h: "12000",
    volume_1h: "900",
    volume_5m: "120",
    buy_count_24h: 68,
    sell_count_24h: 32,
    dex_name: "Raydium",
    trading_pair: "TEST/SOL",
    pool_address: "poolAddress1111111111111111111111111111111",
    trading_status: "trading",
    is_verified: false,
    provider: "dexscreener",
    provider_latency_ms: 120,
    ...overrides,
  };
}

afterEach(cleanup);

describe("VerdictBand — the score comes from the backend", () => {
  it("renders the engine's grade, not one derived from the number", () => {
    render(
      <VerdictBand
        score={tokenScore({ score: "71.4", grade: "strong" })}
        scoreStatus="scored"
        isScorePending={false}
        radar={radarEntry()}
        snapshot={snapshot()}
        capturedAt={new Date().toISOString()}
      />,
    );
    expect(screen.getByRole("meter")).toHaveAttribute(
      "aria-valuetext",
      "71 of 100, Strong",
    );
  });

  it("honours a grade that disagrees with the raw number", () => {
    // The proof that nothing is derived on the client: a high number carrying
    // a low grade must render the grade the engine sent.
    render(
      <VerdictBand
        score={tokenScore({ score: "91", grade: "critical" })}
        scoreStatus="scored"
        isScorePending={false}
        radar={radarEntry()}
        snapshot={snapshot()}
        capturedAt={null}
      />,
    );
    expect(screen.getByRole("meter")).toHaveAttribute(
      "aria-valuetext",
      "91 of 100, Critical",
    );
  });

  it("states the backend status rather than a zero when unscored", () => {
    render(
      <VerdictBand
        score={null}
        scoreStatus="awaiting_market"
        isScorePending={false}
        radar={radarEntry()}
        snapshot={null}
        capturedAt={null}
      />,
    );
    expect(screen.getByText("Awaiting first market observation.")).toBeInTheDocument();
    expect(screen.getByText("Not scored")).toBeInTheDocument();
  });

  it("keeps an unassessed risk unassessed", () => {
    render(
      <VerdictBand
        score={tokenScore()}
        scoreStatus="scored"
        isScorePending={false}
        radar={radarEntry({ risk_band: null })}
        snapshot={snapshot()}
        capturedAt={null}
      />,
    );
    expect(
      screen.getByText("Risk was not assessed for this token"),
    ).toBeInTheDocument();
  });

  it("surfaces a risk veto explicitly", () => {
    render(
      <VerdictBand
        score={tokenScore({ risk: { market_risk: "88", has_veto: true, deduction: "20" } })}
        scoreStatus="scored"
        isScorePending={false}
        radar={radarEntry()}
        snapshot={snapshot()}
        capturedAt={null}
      />,
    );
    expect(screen.getByText(/Risk gate engaged/)).toBeInTheDocument();
  });

  it("shows peak beside current and how much was given back", () => {
    render(
      <VerdictBand
        score={tokenScore()}
        scoreStatus="scored"
        isScorePending={false}
        // 2.0x now against a 4.0x peak — half of it handed back.
        radar={radarEntry({ current_multiple: "2.0", peak_multiple: "4.0" })}
        snapshot={snapshot()}
        capturedAt={null}
      />,
    );
    expect(screen.getByText("2.00×")).toBeInTheDocument();
    expect(screen.getByText("4.00×")).toBeInTheDocument();
    expect(screen.getByText("−50%")).toBeInTheDocument();
  });

  it("renders no market figures as dashes rather than zeros", () => {
    render(
      <VerdictBand
        score={tokenScore()}
        scoreStatus="scored"
        isScorePending={false}
        radar={radarEntry({ market: null })}
        snapshot={null}
        capturedAt={null}
      />,
    );
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("ScoreWaterfall — the working, including the gaps", () => {
  it("shows what each available signal contributed", () => {
    render(<ScoreWaterfall score={tokenScore()} isPending={false} />);
    expect(screen.getByText("Liquidity Depth")).toBeInTheDocument();
    expect(screen.getByText("73")).toBeInTheDocument();
    expect(screen.getByText("18.13")).toBeInTheDocument();
  });

  it("keeps an unavailable signal as a row with its declared weight", () => {
    render(
      <ScoreWaterfall
        score={tokenScore({
          components: [
            component({
              id: "social_sentiment",
              available: false,
              score: null,
              declared_weight: "0.15",
              effective_weight: "0",
              contribution: "0",
            }),
          ],
        })}
        isPending={false}
      />,
    );
    // Dropping the row would quietly turn a 65%-complete model into a
    // finished-looking one and make the coverage figure unexplainable.
    expect(screen.getByText("Social Sentiment")).toBeInTheDocument();
    expect(screen.getByText("15%")).toBeInTheDocument();
    expect(screen.getByText("No data source yet")).toBeInTheDocument();
  });

  it("does not render an unevaluated signal as a score of zero", () => {
    render(
      <ScoreWaterfall
        score={tokenScore({
          components: [component({ available: false, score: null, contribution: "0" })],
        })}
        isPending={false}
      />,
    );
    const row = screen.getAllByRole("row")[1]!;
    expect(within(row).getByText("not evaluated")).toBeInTheDocument();
    expect(within(row).getByText("no contribution")).toBeInTheDocument();
  });

  it("reports the model version and the risk deduction", () => {
    render(<ScoreWaterfall score={tokenScore()} isPending={false} />);
    expect(screen.getByText("v2.1")).toBeInTheDocument();
    expect(screen.getByText("−6.8")).toBeInTheDocument();
  });

  it("says so when no breakdown was published", () => {
    render(<ScoreWaterfall score={null} isPending={false} />);
    expect(
      screen.getByText("No component breakdown has been published for this token."),
    ).toBeInTheDocument();
  });
});

describe("MarketPanel — transactions, not wallets", () => {
  const market = (s: MarketSnapshot | null): TokenMarket => ({
    mint_address: "So11111111111111111111111111111111111111112",
    market: s,
    snapshot_count: 42,
    last_refreshed_at: null,
    next_refresh_at: null,
    enrichment_status: null,
    tier: "priority",
  });

  const token: DiscoveredToken = {
    id: "t1",
    mint_address: "So11111111111111111111111111111111111111112",
    name: "Test Token",
    symbol: "TEST",
    decimals: 6,
    metadata_uri: null,
    image_url: null,
    creator_address: "creator111111111111111111111111111111111",
    signature: "sig",
    slot: 1,
    block_time: "2026-08-01T00:00:00Z",
    discovered_at: "2026-08-01T00:05:00Z",
    source_program: "pump",
    metadata_status: "resolved",
  };

  it("never calls transaction counts buyers or wallets", () => {
    render(<MarketPanel market={market(snapshot())} token={token} />);
    expect(screen.getByText("68 buys")).toBeInTheDocument();
    expect(screen.getByText("32 sells")).toBeInTheDocument();
    expect(
      screen.getByText(/Transaction counts, not unique wallets/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/buyers/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/holders/i)).not.toBeInTheDocument();
  });

  it("says nothing rather than 50% when there were no transactions", () => {
    render(
      <MarketPanel
        market={market(snapshot({ buy_count_24h: 0, sell_count_24h: 0 }))}
        token={token}
      />,
    );
    expect(
      screen.getByText("No transaction counts recorded in the last 24 hours."),
    ).toBeInTheDocument();
  });

  it("reports an unindexed pool as a real state", () => {
    render(<MarketPanel market={market(null)} token={token} />);
    expect(screen.getByText(/No pool has been indexed/)).toBeInTheDocument();
  });

  it("dashes provenance fields it does not have", () => {
    render(
      <MarketPanel
        market={market(snapshot({ trading_pair: null, pool_address: null }))}
        token={token}
      />,
    );
    expect(screen.getByText("Pair not recorded")).toBeInTheDocument();
    expect(screen.getByText("Pool not recorded")).toBeInTheDocument();
  });
});

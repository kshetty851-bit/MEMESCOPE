import { describe, expect, it } from "vitest";

import { selectPackets } from "@/lib/hq/packets";
import type { Source } from "@/lib/hq/adapter";
import type { RadarEntry } from "@/types/radar";
import type { PaperPosition, PaperPositions } from "@/types/paper";

/**
 * TOKEN PACKET SELECTION — acceptance.
 *
 * The two properties that matter: never more than three visible, and the
 * overflow count is real or absent, never guessed.
 */

const NOW = Date.parse("2026-06-01T00:00:00Z");

function radarEntry(mint: string, detectedAt: string): RadarEntry {
  return {
    mint_address: mint,
    name: `Token ${mint}`,
    symbol: mint.slice(0, 4).toUpperCase(),
    category: "early_momentum",
    original_category: "early_momentum",
    opportunity_score: "50",
    confidence: "60",
    first_detected_at: detectedAt,
    first_price: null,
    first_market_cap: null,
    first_liquidity: null,
    first_opportunity_score: "50",
    current_price: null,
    current_market_cap: null,
    current_liquidity: null,
    current_multiple: null,
    peak_multiple: null,
    peak_price: null,
    peak_market_cap: null,
    peak_at: null,
    days_since_detection: "0",
    is_active: true,
    detection_reason: [],
    achieved_tiers: [],
    liveness: "alive",
    model_version: "v1",
    last_evaluated_at: detectedAt,
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

function paperPosition(mint: string, openedAt: string): PaperPosition {
  return {
    mint_address: mint,
    name: `Token ${mint}`,
    symbol: mint.slice(0, 4).toUpperCase(),
    status: "open",
    pricing_status: "priced",
    opened_at: openedAt,
    entry_rank: 1,
    entry_price: "0.001",
    entry_observed_price: null,
    size_usd: "10",
    quantity: "1000",
    entry_execution_model_version: null,
    entry_execution_price_impact_pct: null,
    entry_execution_fee_usd: null,
    entry_execution_route: null,
    entry_execution_quoted_at: null,
    entry_execution_confidence: null,
    entry_execution_fallback_reason: null,
    entry_market_cap: null,
    entry_liquidity_usd: null,
    target_price: null,
    stop_price: null,
    expires_at: null,
    trailing_drawdown: null,
    trailing_stop_price: null,
    current_price: null,
    current_market_cap: null,
    current_pct: null,
    current_price_at: null,
    peak_pct: null,
    closed_at: null,
    exit_price: null,
    exit_observed_price: null,
    exit_execution_model_version: null,
    exit_execution_price_impact_pct: null,
    exit_execution_fee_usd: null,
    exit_execution_route: null,
    exit_execution_quoted_at: null,
    exit_execution_confidence: null,
    exit_execution_fallback_reason: null,
    exit_reason: null,
    manual_action_at: null,
    pnl_usd: null,
    gross_pnl_usd: null,
    fee_usd: null,
    slippage_usd: null,
    net_pnl_usd: null,
    cost_unavailable_reason: null,
  } as PaperPosition;
}

function radarSource(entries: RadarEntry[]): Source<{ items: RadarEntry[] }> {
  return { data: { items: entries }, observedAt: NOW };
}
function positionsSource(items: PaperPosition[]): Source<PaperPositions> {
  return { data: { items, enabled: true, observed_at: "2026-01-01T00:00:00Z" }, observedAt: NOW };
}

describe("packet selection", () => {
  it("never shows more than three, however much real activity exists", () => {
    const many = Array.from({ length: 40 }, (_, i) => radarEntry(`mint-${i}`, `2026-01-01T00:${String(i).padStart(2, "0")}:00Z`));
    const { packets } = selectPackets({ recentRadar: radarSource(many) }, NOW);
    expect(packets.length).toBeLessThanOrEqual(3);
  });

  it("reports overflow only as a real count of the candidate pool", () => {
    const many = Array.from({ length: 10 }, (_, i) => radarEntry(`mint-${i}`, `2026-01-01T00:${String(i).padStart(2, "0")}:00Z`));
    const { packets, overflow } = selectPackets({ recentRadar: radarSource(many) }, NOW);
    expect(overflow).toBe(many.length - packets.length);
  });

  it("omits overflow entirely when no source answered", () => {
    const { overflow } = selectPackets({}, NOW);
    expect(overflow).toBeNull();
  });

  it("never fabricates an overflow count from nothing", () => {
    const { packets, overflow } = selectPackets(
      { recentRadar: radarSource([radarEntry("only-one", "2026-01-01T00:00:00Z")]) },
      NOW,
    );
    expect(packets).toHaveLength(1);
    expect(overflow).toBe(0);
  });

  it("prioritises transitioning mints first", () => {
    const many = Array.from({ length: 5 }, (_, i) => radarEntry(`mint-${i}`, `2026-01-01T00:0${i}:00Z`));
    const { packets } = selectPackets(
      { transitioning: ["mint-live"], recentRadar: radarSource(many) },
      NOW,
    );
    expect(packets[0]!.mint).toBe("mint-live");
    expect(packets[0]!.reason).toBe("transitioning");
  });

  it("picks recent Paper execution over recent discovery", () => {
    const { packets } = selectPackets(
      {
        recentPositions: positionsSource([paperPosition("bought-mint", "2026-01-01T00:00:00Z")]),
        recentRadar: radarSource([radarEntry("discovered-mint", "2026-01-01T00:00:00Z")]),
      },
      NOW,
    );
    const reasons = packets.map((p) => p.reason);
    expect(reasons.indexOf("executed")).toBeLessThan(reasons.indexOf("discovered"));
  });

  it("is deterministic — identical inputs always choose the same three", () => {
    const many = Array.from({ length: 8 }, (_, i) => radarEntry(`mint-${i}`, `2026-01-01T00:0${i}:00Z`));
    const sources = { recentRadar: radarSource(many) };
    const first = selectPackets(sources, NOW).packets.map((p) => p.mint);
    const second = selectPackets(sources, NOW).packets.map((p) => p.mint);
    expect(first).toEqual(second);
  });

  it("never duplicates a mint across selection priorities", () => {
    const shared = paperPosition("shared-mint", "2026-01-01T00:00:00Z");
    const { packets } = selectPackets(
      {
        transitioning: ["shared-mint"],
        recentPositions: positionsSource([shared]),
        recentRadar: radarSource([radarEntry("shared-mint", "2026-01-01T00:00:00Z")]),
      },
      NOW,
    );
    const mints = packets.map((p) => p.mint);
    expect(new Set(mints).size).toBe(mints.length);
  });

  it("carries no symbol/name it was not actually given", () => {
    const { packets } = selectPackets({ transitioning: ["unknown-mint"] }, NOW);
    expect(packets[0]!.symbol).toBeNull();
    expect(packets[0]!.name).toBeNull();
  });
});

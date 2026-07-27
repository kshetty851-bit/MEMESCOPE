import { describe, expect, it } from "vitest";

import { deriveIntelligence } from "@/lib/intelligence";
import type { DiscoveredToken, MarketSnapshot } from "@/types/api";

/**
 * These heuristics drive every verdict a user sees, including the gold Elite
 * Gem treatment. The rules that matter most are the negative ones: an
 * unobserved token must never be given a verdict, and gold must stay rare.
 */

function token(overrides: Partial<DiscoveredToken> = {}): DiscoveredToken {
  return {
    id: "id-1",
    mint_address: "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump",
    name: "Test Token",
    symbol: "TEST",
    decimals: 6,
    metadata_uri: null,
    creator_address: "Wallet1",
    signature: "sig",
    slot: 1,
    block_time: null,
    discovered_at: new Date().toISOString(),
    source_program: "pump",
    metadata_status: "resolved",
    ...overrides,
  };
}

function market(overrides: Partial<MarketSnapshot> = {}): MarketSnapshot {
  return {
    id: "snap-1",
    mint_address: "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump",
    captured_at: new Date().toISOString(),
    price_usd: "0.0000042",
    price_native: "0.00000002",
    liquidity_usd: "50000",
    fully_diluted_valuation: "200000",
    market_cap: "200000",
    volume_24h: "288000",
    volume_1h: "12000",
    volume_5m: "1000",
    buy_count_24h: 700,
    sell_count_24h: 300,
    dex_name: "pumpswap",
    trading_pair: "TEST/SOL",
    pool_address: "pool1",
    trading_status: "trading",
    is_verified: false,
    provider: "dexscreener",
    provider_latency_ms: 300,
    ...overrides,
  };
}

describe("deriveIntelligence", () => {
  it("marks an unobserved token provisional and never certifies it", () => {
    const intel = deriveIntelligence(token(), null);
    expect(intel.provisional).toBe(true);
    expect(intel.elite).toBe(false);
  });

  it("does not certify a token with thin liquidity", () => {
    // Gold must stay rare. A hyped token with no exit is the exact shape
    // Sentinel exists to stop.
    const intel = deriveIntelligence(
      token(),
      market({ liquidity_usd: "50", market_cap: "5000000", volume_24h: "900000" }),
    );
    expect(intel.elite).toBe(false);
    expect(intel.risk.score).toBeGreaterThan(0.5);
  });

  it("raises momentum when 5m volume outruns the 24h baseline", () => {
    const calm = deriveIntelligence(token(), market({ volume_5m: "100" }));
    const spiking = deriveIntelligence(token(), market({ volume_5m: "20000" }));
    expect(spiking.momentum.score).toBeGreaterThan(calm.momentum.score);
  });

  it("treats heavy sell pressure as risk", () => {
    const buying = deriveIntelligence(
      token(),
      market({ buy_count_24h: 900, sell_count_24h: 100 }),
    );
    const dumping = deriveIntelligence(
      token(),
      market({ buy_count_24h: 100, sell_count_24h: 900 }),
    );
    expect(dumping.risk.score).toBeGreaterThan(buying.risk.score);
  });

  it("reads large average trade size as whale activity", () => {
    const retail = deriveIntelligence(
      token(),
      market({ volume_24h: "10000", buy_count_24h: 5000, sell_count_24h: 5000 }),
    );
    const whales = deriveIntelligence(
      token(),
      market({ volume_24h: "500000", buy_count_24h: 50, sell_count_24h: 50 }),
    );
    expect(whales.whale.score).toBeGreaterThan(retail.whale.score);
  });

  it("penalises unresolved metadata", () => {
    const resolved = deriveIntelligence(token(), market());
    const pending = deriveIntelligence(
      token({ metadata_status: "pending" }),
      market(),
    );
    expect(pending.risk.score).toBeGreaterThan(resolved.risk.score);
  });

  it("keeps every score inside 0–1", () => {
    const extreme = deriveIntelligence(
      token(),
      market({
        volume_5m: "999999999",
        volume_24h: "999999999",
        liquidity_usd: "0",
        market_cap: "999999999",
        buy_count_24h: 0,
        sell_count_24h: 999999,
      }),
    );
    for (const value of [
      extreme.momentum.score,
      extreme.risk.score,
      extreme.whale.score,
      extreme.community.score,
      extreme.confidence,
      extreme.gemProbability,
    ]) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
    }
  });

  it("survives junk values from the provider", () => {
    const intel = deriveIntelligence(
      token(),
      market({ price_usd: "not-a-number", volume_24h: "", liquidity_usd: null }),
    );
    expect(Number.isFinite(intel.confidence)).toBe(true);
  });

  it("gem probability never exceeds confidence", () => {
    // Gem answers "is this exceptional?", which must be a stricter bar than
    // "is this fine?".
    const intel = deriveIntelligence(token(), market());
    expect(intel.gemProbability).toBeLessThanOrEqual(intel.confidence);
  });
});

import type { TokenIntelligence } from "@/lib/intelligence";
import type { DiscoveredToken, MarketSnapshot } from "@/types/api";

/**
 * TOKEN LIFECYCLE
 *
 * Detected → Analysing → Scored → Elite
 *
 * Every stage is read from real backend state. There is no timer, no fake
 * progress bar and no optimistic advance: a card sits in Detected for as long
 * as the enrichment worker actually takes, which on mainnet is one to two
 * minutes. Showing a token "analysing" when nothing is analysing it would be
 * the single most dishonest thing this interface could do.
 *
 *   Detected   — discovered on-chain, no market observation yet
 *   Analysing  — provider returned a pool but has not classified it
 *   Scored     — a full observation exists and the division has a verdict
 *   Elite      — Apex granted classification
 */

export type LifecycleStage = "detected" | "analysing" | "scored" | "elite";

export const STAGE_ORDER: LifecycleStage[] = [
  "detected",
  "analysing",
  "scored",
  "elite",
];

export const STAGE_LABEL: Record<LifecycleStage, string> = {
  detected: "Detected",
  analysing: "Analysing",
  scored: "Scored",
  elite: "Elite",
};

export const STAGE_TONE: Record<LifecycleStage, string> = {
  detected: "var(--color-scout)",
  analysing: "var(--color-plasma)",
  scored: "var(--color-oracle)",
  elite: "var(--color-apex)",
};

export function lifecycleStage(
  // Retained in the signature: the next stage split (metadata resolution) reads
  // from the token, and changing every call site later is not worth saving a
  // parameter now.
  _token: DiscoveredToken,
  market: MarketSnapshot | null,
  intel: TokenIntelligence,
): LifecycleStage {
  if (intel.elite) return "elite";
  if (!market) return "detected";
  // A pool exists but the provider has not resolved whether it is tradeable —
  // the observation is genuinely incomplete.
  if (market.trading_status === "unknown") return "analysing";
  return "scored";
}

/** 0–1 progress through the pipeline, for the stage rail. */
export function stageProgress(stage: LifecycleStage): number {
  return STAGE_ORDER.indexOf(stage) / (STAGE_ORDER.length - 1);
}

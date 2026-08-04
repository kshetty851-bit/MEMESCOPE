/**
 * Opportunity Radar API contracts.
 *
 * Mirrors `backend/app/radar/schemas.py`. Every numeric field arrives as a
 * **string** — the backend serialises `Decimal` that way so a JSON float cannot
 * silently round the multiples the track record is judged on. Parse at the edge
 * of rendering with `num()`, never store the parsed value.
 */

export type RadarCategory =
  "early_momentum" | "breakout" | "strong_community" | "undervalued" | "elite";

export type RadarDimensionId =
  "onchain_health" | "momentum" | "technical" | "liquidity_quality" | "community" | "risk";

export interface RadarDimension {
  id: RadarDimensionId;
  label: string;
  /** False when the signal has no data source. Never rendered as zero. */
  available: boolean;
  score: string | null;
  effective_weight: string | null;
  reasons: string[];
}

export interface RadarReason {
  code: string;
  agent: string;
  severity: "info" | "positive" | "caution" | "critical";
  /** Rendered by the backend. The client never composes these. */
  message: string;
}

export interface RadarAchievement {
  tier: string;
  multiple: string;
  achieved_at: string;
  price_at_achievement: string | null;
  market_cap_at_achievement: string | null;
  days_to_achieve: string | null;
}

export interface RadarEntry {
  mint_address: string;
  name: string | null;
  symbol: string | null;

  category: RadarCategory;
  /** The category at first detection, kept beside the current one. */
  original_category: RadarCategory;
  opportunity_score: string;
  confidence: string;

  /** Written once, never updated. Every return is measured from these. */
  first_detected_at: string;
  first_price: string | null;
  first_market_cap: string | null;
  first_liquidity: string | null;
  first_opportunity_score: string;

  current_price: string | null;
  current_market_cap: string | null;
  current_liquidity: string | null;

  /** Multiples from detection: "1.0" is unchanged, "2.0" is a double. */
  current_multiple: string | null;
  peak_multiple: string | null;
  peak_price: string | null;
  peak_market_cap: string | null;
  peak_at: string | null;
  days_since_detection: string;

  is_active: boolean;
  detection_reason: string[];
  /** Tiers ever reached, from the achievement record. Permanent once earned. */
  achieved_tiers: string[];
  model_version: string;
  last_evaluated_at: string;
}

export interface RadarDetail extends RadarEntry {
  dimensions: RadarDimension[];
  reasons: RadarReason[];
  achievements: RadarAchievement[];
}

export interface RadarPage {
  items: RadarEntry[];
  total: number;
  page: number;
  page_size: number;
  applied_filters: Record<string, unknown>;
}

export interface RadarSnapshot {
  captured_at: string;
  price: string | null;
  market_cap: string | null;
  liquidity: string | null;
  opportunity_score: string;
  confidence: string;
  coverage: string;
  category: RadarCategory;
  reasons: string[];
}

export interface RadarHistory {
  mint_address: string;
  items: RadarSnapshot[];
  total: number;
}

export interface TierCount {
  tier: string;
  count: number;
}

export interface RadarPerformance {
  total_opportunities: number;
  active_opportunities: number;
  average_peak_multiple: string | null;
  median_current_multiple: string | null;
  best_peak_multiple: string | null;
  worst_current_multiple: string | null;
  tiers: TierCount[];
  /** Share that reached 2x, over everything ever detected — losers included. */
  success_rate: string | null;

  /**
   * Track-record aggregates. Every one is measured over the permanent record;
   * `null` means no row supports the figure and the page renders "—".
   */
  expired_opportunities: number;
  median_peak_multiple: string | null;
  average_drawdown: string | null;
  average_days_to_2x: string | null;
  average_days_tracked: string | null;
  average_detection_market_cap: string | null;
  average_peak_market_cap: string | null;
  largest_peak_market_cap: string | null;
  observed_at: string | null;
}

export interface RadarCategorySpec {
  id: RadarCategory;
  label: string;
  description: string;
  /** False when the current model can never award it. */
  reachable: boolean;
  reachable_note: string | null;
}

export interface RadarModel {
  version: string;
  dimensions: { id: string; label: string; weight: string; available: boolean }[];
  declared_weight_total: string;
  available_weight_total: string;
  min_radar_score: string;
  min_radar_confidence: string;
  min_risk_floor: string;
  categories: RadarCategorySpec[];
  achievement_tiers: string[];
}

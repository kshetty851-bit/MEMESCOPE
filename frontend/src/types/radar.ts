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

/**
 * Price, size and flow as last observed. Shared verbatim with the Opportunity
 * board — one object, two surfaces, so they cannot disagree about a token.
 *
 * The whole object is nullable and so is every field: a token nobody has
 * priced must render as "no market data", never as being worth zero.
 */
export interface MarketStrip {
  price_usd: string | null;
  market_cap: string | null;
  liquidity_usd: string | null;
  volume_24h: string | null;
  /** Null when no reading exists from a full 24h back. Never 0%. */
  change_24h_pct: string | null;
  captured_at: string | null;
  dex_name: string | null;
}

/**
 * The live signal beside a Radar row. Null means nothing is live right now —
 * never that nothing ever happened.
 *
 * Deliberately narrow: `provider`, `severity`, `strength`, `confirmations` and
 * the engine's own `confidence` are not on this surface. They are accurate and
 * internal, and a reader who sees `confidence: 61.53` will read it as a
 * probability, which it is not.
 */
export interface RadarSignal {
  /** A stable code to branch on. Never printed — an unlabelled type is absent. */
  signal_type: string;
  /** Rendered by the backend in trader language. Displayed verbatim. */
  label: string;
  expires_in_seconds: number;
}

/**
 * Why this row is interesting now, in one sentence. Present on every entry.
 *
 * Rendered server-side from stored facts. `code` is what the client keys on;
 * `sentence` is what it displays. The client composes neither.
 */
export interface WhyNow {
  code: string;
  sentence: string;
}

export interface RadarEntry {
  mint_address: string;
  name: string | null;
  symbol: string | null;
  image_url?: string | null;

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
  /** `alive` | `unknown`. Never `inactive` — nothing establishes death. */
  liveness: string;
  model_version: string;
  last_evaluated_at: string;

  /** How past detections in this category actually performed. Not a forecast. */
  base_rate: BaseRate | null;

  market: MarketStrip | null;
  /** Seconds since the mint existed on chain. Null when unknown, never 0. */
  age_seconds: number | null;
  /**
   * Risk from the last recorded sweep, 0–100, scored like every other
   * dimension — so a **low** number is the dangerous one. Null when the sweep
   * had no source, which is charged to `evidence` rather than hidden.
   */
  risk_score: string | null;
  /**
   * `low` | `medium` | `high` | `extreme`, cut on the server against published
   * thresholds. Null means risk was not assessed — an absence, not a fifth
   * band, and it must never render as one.
   */
  risk_band: string | null;
  risk_reasons: string[];
  /** Share of the model's weight that had data, 0–100. The honesty number. */
  evidence: string | null;
  signal: RadarSignal | null;
  why_now: WhyNow | null;
}

/**
 * What happened to past detections of this kind. Measured history, never a
 * forecast — it makes no claim about the token in front of you.
 *
 * When `sufficient` is false the surface must print `insufficient_reason`
 * instead of a percentage: a rate from n=1 is noise wearing evidence's costume.
 */
export interface BaseRate {
  category: string;
  sample: number;
  reached_2x: number;
  reached_5x: number;
  reached_10x: number;
  reached_100x: number;
  median_peak_multiple: string | null;
  median_current_multiple: string | null;
  sufficient: boolean;
  insufficient_reason: string | null;
  minimum_sample: number;
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
  average_current_multiple: string | null;
  average_days_to_5x: string | null;
  above_entry: number;
  below_entry: number;
  alive: number;
  unknown: number;
  inactive: number;
  last_detection_at: string | null;
  observed_at: string | null;
}

export interface RadarTimelineEvent {
  kind: string;
  mint_address: string;
  name: string | null;
  symbol: string | null;
  image_url?: string | null;
  occurred_at: string;
  tier: string | null;
  market_cap: string | null;
  value: string | null;
}

export interface FreshDetectedToken {
  mint_address: string;
  name: string | null;
  symbol: string | null;
  image_url?: string | null;
  discovered_at: string;
  block_time: string | null;
  metadata_status: string;
  current_market_cap: string | null;
  current_liquidity: string | null;
  current_price: string | null;
  market_observed_at: string | null;
  radar_score: string | null;
  radar_category: string | null;
  radar_status: string | null;
}

export interface RadarBenchmark {
  entries: number;
  average_current_multiple: string | null;
  average_peak_multiple: string | null;
  median_current_multiple: string | null;
  above_entry: number;
  below_entry: number;
  /** Why holding SOL is not shown. Measured absence, stated. */
  sol_note: string;
  paper_wallet_note: string;
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

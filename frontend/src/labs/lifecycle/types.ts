/**
 * MEME LIFECYCLE LAB — wire types.
 *
 * Transcribed from "API response contract" in docs/MEME_LIFECYCLE_LAB.md. Money,
 * prices and ratios are Decimal STRINGS (or null); they become numbers only at
 * display time. A derived value that could not be computed is a `Measured`, never
 * a bare 0 — absence and zero are different facts and the UI keeps them apart.
 */

export type DecimalString = string;
export type IsoTimestamp = string;

/** A derived figure that may not exist. `value: null` means UNAVAILABLE, not zero. */
export interface Measured {
  value: DecimalString | null;
  unavailable_reason: string | null;
}

export type SourceStatus =
  | "available"
  | "unavailable"
  | "disabled"
  | "error"
  | "stale"
  | "partial"
  | "never_collected";

export type DataClass = "forward" | "backfill";

export interface SourceHealth {
  source: string;
  label: string;
  status: SourceStatus;
  reason: string | null;
  last_run_at: IsoTimestamp | null;
  data_class: DataClass;
  observations_24h: number | null;
}

export interface Portfolio {
  run_id: string | null;
  as_of: IsoTimestamp | null;
  starting_capital: DecimalString;
  equity: DecimalString | null;
  cash: DecimalString | null;
  deployed: DecimalString | null;
  realized_pnl: DecimalString | null;
  unrealized_pnl: DecimalString | null;
  roi: DecimalString | null;
  drawdown: DecimalString | null;
  trades: number;
  open_positions: number;
  sample_label: string;
  unavailable_reason: string | null;
}

export interface ExperimentSplit {
  experiment_key: string;
  split_meaningful: boolean;
  split_note: string;
  train: [IsoTimestamp, IsoTimestamp];
  validation: [IsoTimestamp, IsoTimestamp];
  test: [IsoTimestamp, IsoTimestamp];
}

export type LabMode = "authoritative" | "exploratory";

export type ResearchState =
  | "NOT_STARTED"
  | "COLLECTING"
  | "INSUFFICIENT_DATA"
  | "READY_FOR_ANALYSIS"
  | "ANALYZING"
  | "AUTHORITATIVE_RESULT";

export interface ResearchRequirement {
  key: string;
  label: string;
  threshold: string;
  /** null = could not be measured; then `met` is false and `reason` says why. */
  observed: string | null;
  met: boolean;
  reason: string | null;
}

export interface ResearchStatus {
  state: ResearchState;
  /**
   * "UNCERTAIN" in every state except AUTHORITATIVE_RESULT. Typed as string
   * because the verdict engine is not built yet and its vocabulary is not
   * part of this phase's contract.
   */
  verdict: string;
  verdict_engine_available: boolean;
  forward_start: IsoTimestamp | null;
  forward_days: number | null;
  experiment_key: string | null;
  requirements: ResearchRequirement[];
  explanation: string;
}

export interface LifecycleOverview {
  lab_enabled: boolean;
  real_trading: boolean;
  mode: LabMode;
  forward_start: IsoTimestamp | null;
  forward_days: number | null;
  portfolio: Portfolio;
  experiment: ExperimentSplit | null;
  sources: SourceHealth[];
  tracked_memes: number;
  linked_tokens: number;
  notes: string[];
  /** Same object as GET /research-status (validation phase). */
  research_status: ResearchStatus;
}

export interface LifecycleHealth {
  generated_at: IsoTimestamp;
  sources: SourceHealth[];
}

export interface TokenLink {
  mint: string;
  symbol: string | null;
  name: string | null;
  link_method: string;
  confidence: DecimalString;
  linked_at: IsoTimestamp;
}

export interface AttentionMeasures {
  mentions_1h: Measured;
  mentions_24h: Measured;
  velocity: Measured;
  acceleration: Measured;
  baseline_multiple: Measured;
  platform_count: Measured;
}

export type PaperStatus = "none" | "open" | "closed";

export interface MemeRow {
  slug: string;
  display_name: string;
  tokens: TokenLink[];
  primary_mint: string | null;
  token_age_seconds: number | null;
  age_bucket: string | null;
  market_cap: DecimalString | null;
  liquidity_usd: DecimalString | null;
  volume_1h: DecimalString | null;
  price_change_1h: DecimalString | null;
  attention: AttentionMeasures;
  lifecycle_state: string | null;
  market_activity: Measured;
  data_freshness_seconds: number | null;
  paper_status: PaperStatus;
  contains_backfill: boolean;
}

export interface MemeList {
  generated_at: IsoTimestamp;
  items: MemeRow[];
}

export interface SeriesPoint {
  t: IsoTimestamp;
  /** null = unavailable at that bucket. NOT zero. */
  value: DecimalString | null;
}

export interface MemeSeries {
  attention: SeriesPoint[];
  price: SeriesPoint[];
  volume: SeriesPoint[];
  per_source: Record<string, SeriesPoint[]>;
  /** Points before this instant are exploratory (backfill). */
  backfill_before: IsoTimestamp | null;
}

export type MarkerKind =
  | "token_launch"
  | "attention_spike"
  | "attention_acceleration"
  | "revival"
  | "wave"
  | "paper_entry"
  | "paper_exit"
  // The contract says "..." — the server may add kinds; the chart has a
  // fallback glyph for any it does not know.
  | (string & {});

export interface ChartMarker {
  t: IsoTimestamp;
  kind: MarkerKind;
  label: string;
  event_type: string | null;
  mint: string | null;
}

export interface MemeIdentity {
  slug: string;
  display_name: string;
  description: string | null;
  tracking_started_at: IsoTimestamp | null;
  wikipedia_title: string | null;
  gdelt_query: string | null;
}

export interface MemeAlias {
  alias: string;
  kind: string;
  added_at: IsoTimestamp | null;
}

export interface MemeLink {
  mint: string;
  method: string;
  confidence: DecimalString;
  linked_at: IsoTimestamp;
  unlinked_at: IsoTimestamp | null;
}

export interface MemeEvent {
  event_type: string;
  detected_at: IsoTimestamp;
  mint: string | null;
  divergence_case: string | null;
  lifecycle_state: string | null;
  mode: LabMode | string;
  contains_backfill: boolean;
  /** Keyed by horizon: "5m" … "24h". */
  returns: Record<string, Measured>;
  price_at_detection: DecimalString | null;
  run_up_before_detection: Measured;
}

export interface EvidenceStep {
  at: IsoTimestamp;
  kind: string;
  detail: string | null;
}

export interface PaperTrade {
  trade_key: string;
  mint: string;
  entry_at: IsoTimestamp;
  entry_price: DecimalString | null;
  size_usd: DecimalString;
  exit_at: IsoTimestamp | null;
  exit_price: DecimalString | null;
  exit_reason: string | null;
  pnl_usd: DecimalString | null;
  return_pct: DecimalString | null;
  status: string;
  entry_reason: string | null;
  evidence_timeline: EvidenceStep[];
}

export type DataLabel = "authoritative" | "exploratory";

export interface MemeDetail {
  meme: MemeIdentity;
  aliases: MemeAlias[];
  links: MemeLink[];
  series: MemeSeries;
  markers: ChartMarker[];
  events: MemeEvent[];
  trades: PaperTrade[];
  data_label: DataLabel;
  contains_backfill: boolean;
  sources: SourceHealth[];
}

// ---- validation phase: GET /quality ----------------------------------------

export interface ObservationSplit {
  forward: number;
  backfill: number;
}

export interface SourceCollectionStats {
  source: string;
  label: string;
  runs_24h: number;
  available: number;
  unavailable: number;
  disabled: number;
  error: number;
  stale: number;
  partial: number;
  /** AVAILABLE / (runs - DISABLED). null when that denominator is zero. */
  success_rate_24h: DecimalString | null;
  last_success_at: IsoTimestamp | null;
  /** A SourceStatus value; kept as string so a new status cannot break the page. */
  last_status: string | null;
  last_reason: string | null;
}

export interface CollectionStats {
  runs_24h: number;
  failures_24h: number;
  success_rate_24h: DecimalString | null;
  by_source: SourceCollectionStats[];
}

export interface QualityMemeRef {
  slug: string;
  display_name: string;
}

export interface QualityTokenRef {
  mint: string;
  meme_slug: string;
}

export interface QualityIncompleteToken extends QualityTokenRef {
  missing: string[];
}

export interface QualityReport {
  generated_at: IsoTimestamp;
  tracked_memes: number;
  tracked_tokens: number;
  observations_today: ObservationSplit;
  observations_week: ObservationSplit;
  collection: CollectionStats;
  unavailable_sources: string[];
  stale_sources: string[];
  oldest_forward_observation_at: IsoTimestamp | null;
  newest_forward_observation_at: IsoTimestamp | null;
  memes_without_observations: QualityMemeRef[];
  tokens_without_market_history: QualityTokenRef[];
  tokens_with_incomplete_market_data: QualityIncompleteToken[];
}

// ---- validation phase: GET /memes/{slug}/quality ---------------------------

/**
 * `evidence` is named but not shaped by the contract. The renderer accepts a
 * string, a flat object, or null and never assumes more.
 */
export type LinkEvidence = string | Record<string, unknown> | unknown[] | null;

export interface AuditLink extends MemeLink {
  linked_by: string | null;
  evidence: LinkEvidence;
}

export interface AuditSource {
  source: string;
  label: string;
  status: SourceStatus;
  reason: string | null;
  first_observation_at: IsoTimestamp | null;
  latest_observation_at: IsoTimestamp | null;
  observation_count: number;
  forward_count: number;
  backfill_count: number;
}

export interface AuditMarket {
  mint: string;
  first_observation_at: IsoTimestamp | null;
  latest_observation_at: IsoTimestamp | null;
  observation_count: number;
  missing_fields: string[];
}

export interface AuditAttention {
  mentions_1h: Measured;
  velocity: Measured;
  acceleration: Measured;
  baseline_multiple: Measured;
}

export type CollectionPriorityLevel = "low" | "normal" | "high";

export interface CollectionPriority {
  level: CollectionPriorityLevel | (string & {});
  interval_seconds: number;
  reason: string;
}

export interface MemeQuality {
  meme: MemeIdentity;
  aliases: MemeAlias[];
  links: AuditLink[];
  sources: AuditSource[];
  market: AuditMarket[];
  lifecycle_state: string | null;
  attention: AuditAttention;
  divergence_case: string | null;
  collection_priority: CollectionPriority;
}

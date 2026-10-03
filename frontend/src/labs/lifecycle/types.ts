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

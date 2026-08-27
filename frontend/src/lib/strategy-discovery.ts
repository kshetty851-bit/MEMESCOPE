import { api } from "@/lib/api-client";

/**
 * STRATEGY DISCOVERY CLIENT.
 *
 * A search is read, never started, from the browser: the engine evaluates
 * thousands of definitions and is run by an operator on the host. There is no
 * mutating call in this module, and the API has no route that would accept one.
 *
 * `dataset_source` is carried on every request and rendered on every surface.
 * Local and production are different databases (§31) and a figure from one must
 * never be read as evidence about the other.
 */

export type DiscoveryDataset = "LOCAL_BACKTEST" | "PRODUCTION_FORWARD_RESEARCH";
export type DiscoveryBlock = "DISCOVERY" | "VALIDATION" | "HOLDOUT" | "WALK_FORWARD";
export type CandidateStatus =
  | "GENERATED"
  | "DISCOVERY"
  | "VALIDATION"
  | "HOLDOUT"
  | "CHAMPION"
  | "FAILED";

export const DISCOVERY_BLOCKS: DiscoveryBlock[] = [
  "DISCOVERY",
  "VALIDATION",
  "HOLDOUT",
  "WALK_FORWARD",
];

export const BLOCK_LABEL: Record<DiscoveryBlock, string> = {
  DISCOVERY: "Discovery (in-sample)",
  VALIDATION: "Validation (out-of-sample)",
  HOLDOUT: "Final holdout (sealed)",
  WALK_FORWARD: "Walk-forward (primary OOS evidence)",
};

export interface DiscoveryFunnel {
  generated: number;
  discovery_survivors: number;
  validation_survivors: number;
  holdout_survivors: number;
  champions: number;
}

export interface SplitDiagnosis {
  calendar_days: number;
  substantial_days: number;
  largest_day_share_pct: number;
  granularity: string;
  warnings: string[];
}

export interface DiscoverySplit {
  granularity: string;
  discovery: { from: string | null; to: string | null };
  validation: { from: string | null; to: string | null };
  holdout: { from: string | null; to: string | null };
  sizes: { discovery: number; validation: number; holdout: number };
  diagnosis: SplitDiagnosis;
  walk_forward_folds: number;
}

export interface DiscoveryOverview {
  banner: string;
  dataset_source: DiscoveryDataset;
  has_run: boolean;
  run_id?: string;
  started_at?: string;
  finished_at?: string | null;
  runtime_seconds?: number | null;
  schedule_resolutions?: number;
  engine_version?: string;
  space_version?: string;
  scoring_version?: string;
  canonical_version?: string;
  universe_usable?: number;
  exclusions?: Record<string, number>;
  split?: DiscoverySplit;
  funnel?: DiscoveryFunnel;
  search_space?: Record<string, unknown>;
  ranking?: string;
  evidence_floor_n?: number;
  preferred_n?: number;
  min_capture_pct?: number;
}

export interface DiscoverySpace {
  banner: string;
  dataset_source: DiscoveryDataset;
  summary: Record<string, unknown>;
  entries: { key: string; label: string; family: string; rule: string }[];
  sizes: string[];
  legacy_size: string;
  profits: { key: string; label: string; rule: string }[];
  exits: { key: string; label: string; family: string; rule: string }[];
  portfolios: { key: string; label: string; rule: string }[];
  unavailable_features: Record<string, string>;
  future_features_not_ready: string;
  notes: string[];
}

export interface DiscoveryRow {
  rank: number;
  strategy_id: string;
  version: string;
  definition_hash: string;
  explanation: string;
  factors: Record<string, string>;
  entry_rules: string;
  size: string;
  profit: string;
  exit: string;
  portfolio: string;
  reference: boolean;
  status: CandidateStatus;
  n: number;
  offered: number;
  capture_pct: number | null;
  final_equity: number | null;
  return_pct: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  max_drawdown_pct: number | null;
  win_rate_pct: number | null;
  rug_loss_usd: number | null;
  score: number | null;
  survives: boolean;
  flags: string[];
  retention_2x: number | null;
  retention_5x: number | null;
  profitable_day_pct: number | null;
  outlier_dependent: boolean;
  outlier_dependent_top3: boolean;
}

export interface DiscoveryCandidates {
  banner: string;
  dataset_source: DiscoveryDataset;
  has_run: boolean;
  block?: DiscoveryBlock;
  run_id?: string;
  rows: DiscoveryRow[];
}

export interface DiscoveryChampions {
  banner: string;
  dataset_source: DiscoveryDataset;
  has_run: boolean;
  verdict?: string;
  next_step?: string;
  standards?: string[];
  champions: {
    strategy_id: string;
    explanation: string;
    definition_hash: string;
    factors: Record<string, string>;
  }[];
}

export interface AttributionLevel {
  level: string;
  n_strategies: number;
  mean_return_pct: string;
  median_return_pct: string;
  mean_profit_factor: string | null;
  mean_capture_pct: string;
  survivors: number;
  survival_pct: string;
}

export interface DiscoveryAttribution {
  banner: string;
  dataset_source: DiscoveryDataset;
  has_run: boolean;
  caveat?: string;
  dimensions: Record<string, AttributionLevel[]>;
}

const BASE = "/strategy-lab/discovery";

export function fetchDiscoveryOverview(
  dataset: DiscoveryDataset,
): Promise<DiscoveryOverview> {
  return api.get<DiscoveryOverview>(`${BASE}/overview?dataset=${dataset}`);
}

export function fetchDiscoverySpace(dataset: DiscoveryDataset): Promise<DiscoverySpace> {
  return api.get<DiscoverySpace>(`${BASE}/space?dataset=${dataset}`);
}

export function fetchDiscoveryCandidates(
  dataset: DiscoveryDataset,
  block: DiscoveryBlock,
  limit = 100,
): Promise<DiscoveryCandidates> {
  return api.get<DiscoveryCandidates>(
    `${BASE}/candidates?dataset=${dataset}&block=${block}&limit=${limit}`,
  );
}

export function fetchDiscoveryChampions(
  dataset: DiscoveryDataset,
): Promise<DiscoveryChampions> {
  return api.get<DiscoveryChampions>(`${BASE}/champions?dataset=${dataset}`);
}

export function fetchDiscoveryAttribution(
  dataset: DiscoveryDataset,
): Promise<DiscoveryAttribution> {
  return api.get<DiscoveryAttribution>(`${BASE}/attribution?dataset=${dataset}`);
}

/** What each discovery flag means, in one line. Shown on hover. */
export const DISCOVERY_FLAG_MEANING: Record<string, string> = {
  NO_EVIDENCE:
    "Fewer than 10 trades. Profit factor, drawdown and win rate are arithmetic on noise here, not measurements.",
  SMALL_SAMPLE: "Fewer than 50 out-of-sample trades — below the preferred bar.",
  LOW_CAPTURE:
    "Takes under 20% of the opportunities it was offered. Preserving capital by not trading is not a strategy.",
  OUTLIER_DEPENDENT: "Unprofitable once its single best trade is removed.",
  OUTLIER_DEPENDENT_TOP3: "Unprofitable once its best three trades are removed.",
  DAY_CONCENTRATED:
    "60% or more of its trades fall on one UTC day. The result describes that day as much as the strategy.",
  NEGATIVE_EXPECTANCY: "Loses money per trade on average.",
  EXCESSIVE_DRAWDOWN: "Peak-to-trough drawdown above the 60% rejection threshold.",
  NO_TRADES: "Took nothing. There is no result here.",
};

export const STATUS_TONE: Record<CandidateStatus, "neutral" | "safe" | "warn" | "danger"> = {
  GENERATED: "neutral",
  DISCOVERY: "neutral",
  VALIDATION: "warn",
  HOLDOUT: "warn",
  CHAMPION: "safe",
  FAILED: "danger",
};

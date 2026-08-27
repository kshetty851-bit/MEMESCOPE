import { api } from "@/lib/api-client";

/**
 * STRATEGY LAB CLIENT — research surfaces, on their own endpoint.
 *
 * Deliberately not a mode flag on the paper client. Strategy Lab shares no
 * capital, no tables and no lineage with either wallet, and a shared fetcher is
 * one bad branch away from rendering a simulated research balance under a
 * wallet heading.
 *
 * Every balance this module returns is **simulated research capital**. The API
 * says so in each payload and the UI repeats it; neither is decoration.
 */

export type LabState = "DISABLED" | "BACKTEST" | "FORWARD_RESEARCH";
export type LabMode = "BACKTEST" | "FORWARD_RESEARCH";
export type LabWindow = "TODAY" | "24H" | "3D" | "7D" | "30D" | "ALL";

export const LAB_WINDOWS: LabWindow[] = ["TODAY", "24H", "3D", "7D", "30D", "ALL"];

export interface LabDataset {
  run_id: string;
  finished_at: string | null;
  canonical_version: string;
  metrics_version: string;
  from: string | null;
  to: string | null;
  candidates: number;
  usable: number;
  excluded: number;
  exclusions: Record<string, number>;
  venues: Record<string, number>;
  observations: number;
}

export interface LabMoonshot {
  level: number;
  reached: number;
  captured: number;
  opportunity_usd: number | null;
  realised_usd: number | null;
  efficiency_pct: number | null;
}

export interface LabRobustness {
  normal_pnl: number;
  ex_best_1_pnl: number;
  ex_best_3_pnl: number;
  ex_worst_1_pnl: number;
  ex_worst_3_pnl: number;
  top_1_share_pct: number | null;
  top_3_share_pct: number | null;
  top_5_share_pct: number | null;
  outlier_dependent: boolean;
}

export interface LabRugImpact {
  count: number;
  capital_invested: number;
  capital_recovered_before: number;
  residual_recovered: number;
  net_loss: number;
  reached_125: number;
  reached_150: number;
  reached_175: number;
  reached_200: number;
}

export interface LabRow {
  rank: number;
  strategy_id: string;
  version: string;
  name: string;
  definition_hash: string;
  benchmark: boolean;
  n: number;
  offered: number;
  starting_capital: number;
  final_equity: number;
  net_pnl: number;
  gross_pnl: number;
  total_costs: number;
  wallet_return_pct: number;
  profit_factor: number | null;
  expectancy: number | null;
  win_rate_pct: number | null;
  median_trade_return_pct: number | null;
  mean_trade_return_pct: number | null;
  max_drawdown_pct: number;
  rug_loss_usd: number;
  rugs: number;
  blocked: number;
  blocked_for_cash: number;
  capital_blocked_usd: number;
  capture_pct: number;
  avg_concurrency: number;
  peak_concurrency: number;
  avg_hold_minutes: number | null;
  unsettled: number;
  day_concentration_pct: number | null;
  moonshots: LabMoonshot[];
  lab_score: number;
  score_components: {
    robust_return_pct: number;
    drawdown: number;
    sample_shrink: number;
    profit_factor_multiplier: number;
  };
  robustness: LabRobustness;
  rug_impact: LabRugImpact;
  flags: string[];
}

export interface LabHeadline {
  strategy_id: string;
  name: string;
  n: number;
  wallet_return_pct: number;
  max_drawdown_pct: number;
  flags: string[];
}

export interface LabOverview {
  title: string;
  banner: string;
  state: LabState;
  mode: LabMode;
  forward_research_active: boolean;
  simulated_capital_notice: string;
  tokens_evaluated: number;
  strategies_running: number;
  simulated_trades: number;
  best_7d: LabHeadline | null;
  best_30d: LabHeadline | null;
  lowest_drawdown: LabHeadline | null;
  highest_moonshot_capture: LabHeadline | null;
  dataset: LabDataset | null;
  execution_model: {
    id: string;
    disclosure: string;
    multi_target_policy: string;
    multi_target_policy_text: string;
  };
}

export interface LabLeaderboard {
  banner: string;
  state: LabState;
  mode: LabMode;
  window: LabWindow;
  window_note: string;
  min_sample: number;
  small_sample_threshold: number;
  ranking: string;
  dataset: LabDataset | null;
  rows: LabRow[];
}

export interface LabStrategyDefinition {
  strategy_id: string;
  version: string;
  name: string;
  purpose: string;
  entry_size_usd: number;
  benchmark: boolean;
  definition_hash: string;
  hold_hours: number;
  rungs: { multiple: number; fraction: number }[];
  runner_fraction: number;
  trailing: {
    drawdown: number;
    activation_multiple: number | null;
    fraction: number;
  } | null;
  decay: { at_minutes: number; never_exceeded: number; at_or_below: number }[];
  min_discovery_age_hours: number | null;
  matrix: Record<string, boolean>;
}

export interface LabStrategies {
  banner: string;
  notes: { s9_gate: string; s3_s10: string; multi_target: string };
  strategies: LabStrategyDefinition[];
}

export interface LabFill {
  at: string;
  reason: string;
  price_usd: string;
  multiple: number;
  quantity_pct_of_initial: number;
  gross_proceeds: number;
  execution_cost: number;
  net_proceeds: number;
  rungs_covered: number[];
  liquidity_usd: number | null;
}

export interface LabTrade {
  mint_address: string;
  opened_at: string;
  closed_at: string | null;
  entry_price: string;
  size_usd: number;
  entry_cost: number;
  entry_liquidity_usd: number | null;
  venue: string | null;
  gross_pnl: number;
  net_pnl: number;
  return_pct: number;
  observed_peak_multiple: number;
  executable_peak_multiple: number;
  terminal_multiple: number | null;
  final_reason: string;
  unsettled: boolean;
  catastrophic: boolean;
  banked_before_final: number;
  fills: LabFill[];
}

export interface LabStrategyDetail {
  banner: string;
  state: LabState;
  mode?: LabMode;
  strategy_id: string;
  name: string;
  version?: string;
  purpose?: string;
  has_results: boolean;
  row?: LabRow;
  wallet?: {
    simulated: boolean;
    starting_balance: number;
    cash: number;
    peak_equity: number;
    open_positions: number;
    closed_positions: number;
  };
  equity_curve?: { at: string; equity: number }[];
  daily_pnl?: { day: string; pnl: number; trades: number }[];
  distribution?: Record<string, number>;
  mean_pnl_ci95?: [number, number] | null;
  best_trades?: LabTrade[];
  worst_trades?: LabTrade[];
  recent_trades?: LabTrade[];
  blocked?: {
    mint_address: string;
    at: string;
    reason: string;
    cash_at_refusal: number;
    peak_multiple: number | null;
  }[];
  dataset: LabDataset | null;
}

export interface LabCompare {
  banner: string;
  mint_address: string;
  opportunity: Record<string, unknown>;
  outcomes: {
    strategy_id: string;
    taken: boolean;
    return_pct?: number;
    net_pnl?: number;
    final_reason?: string;
    fills?: number;
    banked_before_final?: number;
    trade?: LabTrade;
    blocked_reason?: string;
    cash_at_refusal?: number | null;
  }[];
  dataset: LabDataset | null;
}

export interface LabRugs {
  banner: string;
  definition: string;
  control_strategy: string;
  tokens: {
    mint_address: string;
    opened_at: string;
    minutes_to_collapse: number | null;
    executable_peak_multiple: number;
    observed_peak_multiple: number;
    reached_125: boolean;
    reached_150: boolean;
    reached_175: boolean;
    reached_200: boolean;
    strategies: {
      strategy_id: string;
      invested: number;
      recovered_before: number;
      net_pnl: number;
      return_pct: number;
    }[];
  }[];
  by_strategy: {
    strategy_id: string;
    name: string;
    rugs: number;
    capital_invested: number;
    capital_recovered_before: number;
    net_loss: number;
    recovery_pct: number | null;
    reached_125: number;
    reached_150: number;
    reached_175: number;
    reached_200: number;
  }[];
  dataset: LabDataset | null;
}

export interface LabExperiments {
  banner: string;
  matrix: {
    rows: string[];
    columns: string[];
    values: Record<string, Record<string, boolean>>;
  };
  robustness: {
    strategy_id: string;
    name: string;
    n: number;
    normal_pnl: number;
    ex_best_1_pnl: number;
    ex_best_3_pnl: number;
    ex_worst_1_pnl: number;
    ex_worst_3_pnl: number;
    top_1_share_pct: number | null;
    top_3_share_pct: number | null;
    top_5_share_pct: number | null;
    outlier_dependent: boolean;
    flags: string[];
  }[];
  regime: {
    version: string;
    definition: string;
    days: {
      day: string;
      opportunities: number;
      catastrophe_rate_pct: number;
      label: string;
    }[];
  };
  sampling: { in_sample: string; anti_overfitting: string };
  dataset: LabDataset | null;
}

export interface LabStatus {
  banner: string;
  state: LabState;
  states_available: LabState[];
  live_execution_path: string;
  signer: string;
  forward_research_active: boolean;
  forward_wallets: number;
  forward_positions: number;
  tick_seconds: number | null;
  latest_backtest: LabDataset | null;
}

const BASE = "/strategy-lab";

export function fetchLabOverview(mode: LabMode): Promise<LabOverview> {
  return api.get<LabOverview>(`${BASE}/overview?mode=${mode}`);
}

export function fetchLabLeaderboard(
  mode: LabMode,
  window: LabWindow,
): Promise<LabLeaderboard> {
  return api.get<LabLeaderboard>(`${BASE}/leaderboard?mode=${mode}&window=${window}`);
}

export function fetchLabStrategies(): Promise<LabStrategies> {
  return api.get<LabStrategies>(`${BASE}/strategies`);
}

export function fetchLabStrategyDetail(
  strategyId: string,
  mode: LabMode,
): Promise<LabStrategyDetail> {
  return api.get<LabStrategyDetail>(
    `${BASE}/strategies/${encodeURIComponent(strategyId)}?mode=${mode}`,
  );
}

export function fetchLabCompare(mint: string, mode: LabMode): Promise<LabCompare> {
  return api.get<LabCompare>(`${BASE}/compare/${encodeURIComponent(mint)}?mode=${mode}`);
}

export function fetchLabRugs(mode: LabMode): Promise<LabRugs> {
  return api.get<LabRugs>(`${BASE}/rugs?mode=${mode}`);
}

export function fetchLabExperiments(mode: LabMode): Promise<LabExperiments> {
  return api.get<LabExperiments>(`${BASE}/experiments?mode=${mode}`);
}

export function fetchLabStatus(): Promise<LabStatus> {
  return api.get<LabStatus>(`${BASE}/status`);
}

/**
 * Formatting.
 *
 * `null` renders an em dash, never a zero. "We have not measured this" and
 * "this is zero" are different claims, and a research surface that conflated
 * them would be the exact dishonesty the whole subsystem is built to avoid.
 */

export function usd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  return `${sign}$${abs.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function plain(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function multiple(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}x`;
}

export function tone(value: number | null | undefined): "positive" | "negative" | "neutral" {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) {
    return "neutral";
  }
  return value > 0 ? "positive" : "negative";
}

export function shortMint(mint: string): string {
  return mint.length > 12 ? `${mint.slice(0, 6)}…${mint.slice(-4)}` : mint;
}

/** Human label for an exit reason. The enum values are terse on purpose. */
export const FILL_REASON_LABEL: Record<string, string> = {
  target: "Rung",
  trailing_stop: "Trailing stop",
  time_decay: "Time decay",
  expiry: "6h expiry",
  dead_pool: "Dead pool",
  untradable: "Untradable",
  data_unavailable: "No data",
};

/** What each honesty flag means, in one line, shown on hover. */
export const FLAG_MEANING: Record<string, string> = {
  SMALL_SAMPLE: "Fewer than 30 trades. Not enough evidence to rank on.",
  OUTLIER_DOMINATED: "Over half of all profit came from a single trade.",
  OUTLIER_DEPENDENT: "Profitable overall, but unprofitable without its best trade.",
  REGIME_CONCENTRATED:
    "60% or more of these trades were opened on a single UTC day. The result describes that day at least as much as it describes the strategy.",
  INSUFFICIENT_EVIDENCE: "No trades. Nothing here is a result.",
  UNSETTLED_POSITIONS:
    "Some positions ran out of observations while their pool still looked healthy. Their outcome is unknown, not zero.",
};

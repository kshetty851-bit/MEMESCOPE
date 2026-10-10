/**
 * FOREX STRATEGY LAB — wire types (2026-10-10).
 *
 * Mirrors `/api/v1/labs/forex`. Research and paper only: nothing here names a
 * broker, an account or an order.
 *
 * Money (balances, P&L, costs, capital) is a decimal STRING and stays one until
 * display. Percentages, ratios and prices are numbers. A null metric means
 * "not meaningful" and is paired with a note; the page never fills it in.
 *
 * Where the contract leaves a sub-shape open (grid rows, folds, Monte Carlo,
 * regime rows, the baseline), the type is deliberately loose (`Loose`) and the
 * page renders it generically rather than guessing field names. See
 * `generic.tsx`.
 */

/** A stable code plus the prose the API rendered from it. */
export interface Coded {
  code: string;
  text: string;
}

/** An open-ended JSON object whose keys the contract does not pin down. */
export type Loose = Record<string, unknown>;

/** A note is either already rendered `{code,text}` or a bare code. */
export type Note = Coded | string | null;

export type RunKind = "backtest" | "research" | "compare" | "fetch";
export type RunStatus = "queued" | "running" | "done" | "failed";

export type DirectionMode = "both" | "long_only" | "short_only";
export type CsvFormat = "auto" | "generic" | "histdata" | "metatrader";

// --- /meta -------------------------------------------------------------------

export interface InstrumentOut {
  symbol: string;
  base: string;
  quote: string;
  pip_size: number;
  price_decimals: number;
  contract_size: number;
  min_units: number;
  enabled: boolean;
}

export type FieldKind = "int" | "float" | "bool" | "enum" | "session" | "decimal";

export interface FieldSpec {
  path: string;
  label: string;
  kind: FieldKind;
  min?: number | string;
  max?: number | string;
  step?: number | string;
  options?: string[];
  help?: string;
}

export interface SessionJson {
  start_hour: number;
  end_hour: number;
  start_minute: number;
  end_minute: number;
}

export interface ConfigJson {
  strategy: string;
  symbol: string;
  timeframe: string;
  direction: DirectionMode;
  params: Record<string, unknown>;
  costs: Record<string, unknown>;
  risk: Record<string, unknown>;
  session_filter: SessionJson | null;
}

export interface StrategyMeta {
  id: string;
  name: string;
  description: string;
  timeframe: string;
  default_config: ConfigJson;
  param_fields: FieldSpec[];
  default_grid: Record<string, unknown[]>;
}

export interface ProviderOut {
  id: string;
  name: string;
  free: boolean;
  needs_key: boolean;
  notes: string;
  url?: string;
}

export interface MetaOut {
  instruments: InstrumentOut[];
  timeframes: string[];
  risk_options_pct: string[];
  strategies: StrategyMeta[];
  shared_fields: FieldSpec[];
  providers: ProviderOut[];
  target_pcts: number[];
  disclaimer: Coded;
}

// --- Data --------------------------------------------------------------------

export interface DatasetOut {
  symbol: string;
  timeframe: string;
  bars: number;
  start: string;
  end: string;
  sources: string[];
}

export interface QualityGap {
  start: string;
  end: string;
  missing_bars: number;
  kind: string;
}

export interface QualityReport {
  symbol: string;
  timeframe: string;
  bars: number;
  start: string | null;
  end: string | null;
  duplicates: number;
  misaligned: number;
  non_utc: number;
  ohlc_violations: number;
  out_of_order: number;
  expected_bars: number;
  missing_bars: number;
  coverage_pct: number | null;
  gap_count: number;
  largest_gap_bars: number;
  grade: string;
  gaps: QualityGap[];
  notes: Coded[];
  derived_from: "stored" | "resampled_from_1m" | string;
}

export interface ImportBatch {
  id: number;
  symbol: string;
  timeframe: string;
  source: string;
  filename: string;
  rows_total: number;
  rows_accepted: number;
  rows_inserted: number;
  rows_existing: number;
  error_count: number;
  errors: Array<{ line: number; message: string }>;
  detected_format: string;
  start: string | null;
  end: string | null;
  quality: QualityReport | null;
  notes: Coded[];
  created_at: string;
}

export interface FetchSummary {
  provider: string;
  days_ok: number;
  days_empty: number;
  days_failed: number;
  first_day: string | null;
  last_day: string | null;
}

export interface DataOut {
  datasets: DatasetOut[];
  imports: ImportBatch[];
  fetch: FetchSummary | null;
  providers: ProviderOut[];
}

export interface ImportIn {
  symbol: string;
  timeframe: string;
  fmt: CsvFormat;
  utc_offset_minutes: number;
  filename: string;
  content: string;
}

export interface FetchIn {
  provider: "dukascopy";
  symbol: string;
  start_date: string;
  end_date: string;
}

// --- Runs --------------------------------------------------------------------

export interface RunSummary {
  net_return_pct: number | null;
  total_trades: number | null;
  expectancy_r: number | null;
  max_drawdown_pct: number | null;
  profit_factor: number | null;
  verdict_code?: string | null;
}

export interface RunOut {
  id: number;
  kind: RunKind;
  status: RunStatus;
  progress: number;
  message: string | null;
  name: string | null;
  strategy_version_id: number | null;
  config: ConfigJson | null;
  request: Loose;
  data_fingerprint: string | null;
  config_version: number;
  app_version: string;
  summary: RunSummary | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunOptions {
  dev_pct?: number;
  val_pct?: number;
  grid?: Record<string, unknown[]>;
  walk_forward?: { train_days: number; test_days: number };
  mc_iterations?: number;
  stress_multipliers?: number[];
}

export interface RunIn {
  kind: "backtest" | "research" | "compare";
  config?: ConfigJson;
  configs?: ConfigJson[];
  start: string;
  end: string;
  name?: string;
  strategy_version_id?: number;
  options?: RunOptions;
}

export interface VersionOut {
  id: number;
  name: string;
  version: number;
  strategy: string;
  config: ConfigJson;
  notes: string | null;
  created_at: string;
}

export interface VersionIn {
  name: string;
  config: ConfigJson;
  notes?: string;
}

// --- Results -----------------------------------------------------------------

export interface MetricsOut {
  starting_balance: string;
  ending_balance: string;
  net_profit: string;
  net_return_pct: number | null;
  total_trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate_pct: number | null;
  avg_win: string | null;
  avg_loss: string | null;
  largest_win: string | null;
  largest_loss: string | null;
  gross_profit: string;
  gross_loss: string;
  profit_factor: number | null;
  expectancy_usd: string | null;
  expectancy_r: number | null;
  max_drawdown_pct: number | null;
  max_drawdown_usd: string | null;
  sharpe: number | null;
  sortino: number | null;
  sharpe_note: Note;
  longest_win_streak: number;
  longest_loss_streak: number;
  long_trades: number;
  short_trades: number;
  long_net: string | null;
  short_net: string | null;
  long_win_rate: number | null;
  short_win_rate: number | null;
  long_expectancy_r: number | null;
  short_expectancy_r: number | null;
  total_commission: string;
  total_spread_slippage: string;
  total_financing: string;
  costs_pct_of_gross_profit: number | null;
  max_margin_utilization_pct: number | null;
  avg_margin_utilization_pct: number | null;
  avg_trade_duration_minutes: number | null;
  monthly_trade_frequency: number | null;
  exits_ambiguous: number;
  margin_closeouts: number;
  expectancy_t_stat: number | null;
  significance_note: Note;
}

export interface MonthReturn {
  month: string;
  return_pct: number | null;
  pnl?: string | null;
  trades?: number;
  [key: string]: unknown;
}

export interface EquityPointOut {
  t: string;
  balance: string;
  equity: string;
  margin_pct: number | null;
}

export interface DrawdownPointOut {
  t: string;
  dd_pct: number | null;
}

export interface TradeOut {
  id: number;
  direction: "long" | "short";
  signal_time: string;
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  stop_price: number;
  take_profit_price: number | null;
  units: number;
  risk_usd: string;
  gross_pnl: string;
  commission: string;
  spread_slippage_cost: string;
  financing: string;
  net_pnl: string;
  r_multiple: number | null;
  exit_reason: string;
  reason: string;
  ambiguous_exit: boolean;
  duration_minutes: number | null;
}

export interface SkippedText extends Coded {
  count: number;
}

export interface DataInfo {
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  bars: number;
  sources: string[];
  quality_grade: string;
  coverage_pct: number | null;
  lower_tf_available: boolean;
  htf_derived: string;
}

/**
 * The monthly target report. The contract names the content (target rows,
 * profitable/losing months, best/worst, max drawdown, risk of ruin with its
 * assumptions) but not the key names, so every read goes through
 * `targets.ts`, which accepts the plausible spellings.
 */
export type TargetReport = Loose;

export interface BacktestResult {
  type: "backtest";
  data: DataInfo;
  metrics: MetricsOut;
  months: MonthReturn[];
  equity_curve: EquityPointOut[];
  drawdown: DrawdownPointOut[];
  trades: TradeOut[];
  skipped: Record<string, number>;
  skipped_text: SkippedText[];
  assumptions: Coded[];
  targets: TargetReport;
  baseline: Loose;
  monte_carlo: Loose;
  bootstrap: Loose;
}

export interface Window {
  start: string;
  end: string;
}

export interface BacktestSummary {
  window: Window;
  metrics: MetricsOut;
  months: MonthReturn[];
  equity_curve: EquityPointOut[];
  trade_count: number;
}

export interface Scorecard {
  name: string;
  strategy: string;
  rank: number;
  robustness_score: number | null;
  verdict: Coded;
  flags: Coded[];
  full: Loose;
  out_of_sample: Loose;
  stressed: Loose;
  stability: Loose;
}

export interface ResearchResult {
  type: "research";
  split: { development: Window; validation: Window; test: Window };
  optimisation: { space: unknown; rows: Loose[]; best: Loose | null };
  chosen_params: Record<string, unknown>;
  selection_note: Coded | null;
  development: BacktestSummary;
  validation: BacktestSummary;
  test: BacktestSummary;
  walk_forward: { folds: Loose[]; oos_summary: unknown; efficiency: unknown };
  sensitivity: Record<string, Loose[]>;
  stability: Loose;
  cost_stress: Loose[];
  monte_carlo: Loose;
  bootstrap: Loose;
  regimes: Loose[];
  baseline: Loose;
  targets: { full: TargetReport; out_of_sample: TargetReport };
  scorecard: Scorecard;
}

export interface CompareResult {
  type: "compare";
  window: Window;
  split: Loose;
  scorecards: Scorecard[];
  per_strategy: Record<string, Loose>;
}

export type RunResult = BacktestResult | ResearchResult | CompareResult;

export interface RunDetail {
  run: RunOut;
  result: RunResult | null;
}

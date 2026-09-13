/**
 * FOREX LAB — wire types.
 *
 * BACKTEST ONLY. Everything here is computed on the backend by an operator
 * command over stored candles; the page renders and decides nothing. There is
 * no wallet behind any of these numbers, live or paper.
 *
 * `number | null` is used deliberately wherever the backend can genuinely have
 * no answer — a profit factor with no losing trade, a "share of profit" for a
 * run that made no profit. Coercing those to 0 in the client would print a
 * number the backtest never produced.
 */

export interface ConfigSpec {
  step_pips: number;
  levels: number;
  lots: number;
  stop_multiplier: number;
  name: string;
}

export interface ConfigResult {
  config: ConfigSpec;
  start_equity: number;
  final_equity: number;
  total_return_pct: number;
  /** Null means no losing trade at all — over six years, a bug or an empty run. */
  profit_factor: number | null;
  max_drawdown_pct: number;
  trades: number;
  /** Lowest equity the account ever showed, at the worse extreme of a candle. */
  min_equity: number;
  /** True if the account passed through zero. Every ratio above is then void. */
  blown: boolean;
  recenters: number;
  stopouts: number;
  rejected_fills: number;
  fills: number;
  spread_paid: number;
  swap_paid: number;
  recenter_loss: number;
  stopout_loss: number;
  tp_pnl: number;
  per_year: Record<string, number>;
  per_month: Record<string, number>;
  /** Counted over the six FULL years only; 2026 is half a year. */
  years_positive: number;
  years_total: number;
  partial_year_pnl: number | null;
  /** Can exceed 1 when the other months lost money between them. */
  best_month_share: number | null;
}

export interface BuyAndHold {
  name: string;
  entry: number;
  exit: number;
  gross: number;
  swap: number;
  final_equity: number;
  total_return_pct: number;
}

export interface GateVerdict {
  passed: boolean;
  checks: Record<string, boolean>;
}

export interface GateSpec {
  profit_factor_min: number;
  years_positive_min: number;
  years_positive_of: number;
  must_include_year: number;
  max_drawdown_pct_max: number;
  best_month_share_max: number;
  full_years: number[];
  partial_year: number;
}

export interface SweepResult {
  generated_at: string;
  candles: number;
  first_minute: string;
  last_minute: string;
  results: ConfigResult[];
  buy_and_hold: BuyAndHold;
  gate: GateVerdict;
  best_config: string;
}

export interface LatestRun {
  has_run: boolean;
  backtest_only: true;
  run_id?: string;
  created_at?: string;
  symbol: string;
  first_minute?: string;
  last_minute?: string;
  candles?: number;
  git_sha?: string | null;
  best_config?: string;
  gate_passed?: boolean;
  result?: SweepResult;
  window?: { start: string; end: string };
  gate: GateSpec;
}

export interface DataHealth {
  symbol: string;
  /**
   * Which table answered. "published_run" is the normal case on a deployed
   * instance, where the candles are a working set the server does not hold.
   */
  source: "candles" | "published_run" | "empty";
  candles: number;
  first_minute: string | null;
  last_minute: string | null;
  window: { start: string; end: string };
}

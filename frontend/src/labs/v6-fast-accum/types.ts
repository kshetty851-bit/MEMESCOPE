/**
 * V6 FAST-ACCUMULATION LAB — wire types.
 *
 * RESEARCH ONLY. Everything here is computed on the backend from a frozen
 * dataset; the page renders and decides nothing.
 *
 * `number | null` is used deliberately wherever the backend can genuinely have
 * no answer — a profit factor with no losing trades, a censored trade's return.
 * Coercing those to 0 in the client would print a number the experiment never
 * produced, which is the same mistake as coercing a censored trade to a zero
 * return on the backend.
 */

export interface Metrics {
  trades: number;
  censored: number;
  wins: number;
  losses: number;
  win_rate: number;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number | null;
  expectancy: number;
  avg_winner: number;
  avg_loser: number;
  median_return: number;
  cumulative_pnl: number;
  max_drawdown: number;
  sharpe: number | null;
  sortino: number | null;
  rate_2x: number;
  rate_2x_before_stop: number;
  graduation_rate: number;
  median_time_to_2x_s: number | null;
  median_mae: number | null;
  median_mfe: number | null;
  exit_mix: Record<string, number>;
}

export interface GateCheck {
  condition: string;
  status: "PASS" | "FAIL" | "NOT_EVALUABLE";
  detail: string;
}

export interface Fold {
  index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  selected_config: string | null;
  train_trades: number;
  test: Metrics;
}

export interface CensoringRow {
  reason: string;
  censored: number;
  resolved: number;
  censored_pct_of_censored: number;
  resolved_pct_of_resolved: number;
}

export interface RunResult {
  experiment_id: string;
  spec_version: string;
  config_hash: string;
  dataset_version: string;
  git_sha: string | null;
  random_seed: number;
  research_only: true;
  window: {
    start: string;
    end: string;
    span_hours: number;
    tokens: number;
  };
  data_quality: Record<string, unknown> & {
    tokens_total: number;
    tokens_pruned: number;
    tokens_no_samples: number;
    exclusions: Record<string, number>;
  };
  censoring: {
    censored_total: number;
    resolved_total: number;
    censored_share: number;
    by_reason: CensoringRow[];
  };
  strategies: Record<string, Metrics>;
  controls: Record<string, Metrics>;
  control_design: {
    telegram_unavailable: boolean;
    base_equals_control_b: boolean;
    control_c_equals_control_d: boolean;
    distinct_arms: string[];
    why: string;
  };
  walk_forward: { fold: string; status: string; folds: Fold[] };
  walk_forward_secondary: {
    fold: string;
    status: string;
    exploratory_only: boolean;
    note: string;
    folds: Fold[];
  };
  oos: Metrics;
  concentration: {
    total_profit: number;
    best_token_pct: number;
    top5_pct: number;
    median_token_contribution: number;
    profitable_tokens: number;
  };
  bootstrap: Record<string, number | boolean | null>;
  statistics: Record<
    string,
    { raw_p: number; adjusted_p: number; reject_null: boolean; effect_size_d: number }
  >;
  leakage: { passed: boolean; findings: unknown[]; scope: string };
  gate: {
    passed: boolean;
    checks: GateCheck[];
    verdict: string;
    reason: string;
  };
  verdict: string;
  unavailable_overlays: Record<string, string>;
}

export interface LatestRun {
  has_run: boolean;
  research_only: boolean;
  spec_version?: string;
  config_hash?: string;
  experiment_id?: string;
  dataset_version?: string;
  git_sha?: string | null;
  started_at?: string;
  finished_at?: string | null;
  verdict?: string;
  gate_passed?: boolean;
  leakage_passed?: boolean;
  result?: RunResult;
}

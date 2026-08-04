/**
 * Paper wallet API contracts.
 *
 * Mirrors `backend/app/paper/schemas.py`. Every numeric field arrives as a
 * **string** — the backend serialises `Decimal` that way so a JSON float cannot
 * round the figures a track record is judged on.
 *
 * `null` never means zero anywhere in this file. It means the figure has no
 * rows behind it, and every surface must render it as a dash.
 *
 * This is a simulation over stored prices. No wallet is connected, no order is
 * placed, and nothing here is advice.
 */

export interface PaperRule {
  label: string;
  value: string;
}

export interface PaperStrategy {
  id: string;
  name: string;
  version: string;
  summary: string;
  rules: PaperRule[];
  /** False when a strategy is declared but does not trade. */
  operational: boolean;
  unavailable_reason: string | null;
  is_active: boolean;
}

export interface PaperPosition {
  mint_address: string;
  name: string | null;
  symbol: string | null;

  status: string;
  opened_at: string;
  /** The Radar place the token held when it was bought. */
  entry_rank: number;
  entry_price: string;
  size_usd: string;
  quantity: string;

  /** Fixed at entry, never recomputed. */
  target_price: string;
  stop_price: string;
  expires_at: string;

  /** Null for a token nobody has priced since — unmeasured, not worthless. */
  current_price: string | null;
  current_pct: string | null;
  /** For a closed trade this stops at the exit, not at the token's later high. */
  peak_pct: string | null;

  closed_at: string | null;
  exit_price: string | null;
  /** `target` | `stop` | `expiry`. Never `manual`. */
  exit_reason: string | null;
  pnl_usd: string | null;
}

export interface PaperBenchmark {
  id: string;
  label: string;
  description: string;
  return_pct: string | null;
  difference_pct: string | null;
  unavailable_reason: string | null;
}

export interface PaperMetrics {
  starting_balance: string;
  cash: string;
  /** Null when any open holding is unpriced. */
  equity: string | null;
  roi_pct: string | null;
  open_value: string | null;
  unpriced_positions: number;

  open_positions: number;
  closed_positions: number;

  realised_pnl: string;
  win_rate_pct: string | null;
  average_win: string | null;
  average_loss: string | null;
  /** Null while nothing has lost — undefined, not infinite. */
  profit_factor: string | null;
  largest_winner: string | null;
  largest_loser: string | null;
  /** Realised equity curve only. The note says so; display it. */
  max_drawdown_pct: string | null;
  max_drawdown_note: string;
  average_hold_hours: string | null;
  exits_by_reason: Record<string, number>;
}

export interface PaperWallet {
  /** False when the feature flag is off — not the same as "traded nothing". */
  enabled: boolean;
  strategy: PaperStrategy;
  metrics: PaperMetrics;
  benchmarks: PaperBenchmark[];
  /** Realised profit since midnight UTC. Realised only. */
  pnl_today: string;
  /** Rendered on every surface that shows the numbers. */
  disclosure: string;
  observed_at: string;
}

export interface PaperPositions {
  items: PaperPosition[];
  enabled: boolean;
  observed_at: string;
}

export interface PaperStrategies {
  items: PaperStrategy[];
  active_id: string;
}

// --- Strategy Lab -------------------------------------------------------------

export interface LabRule {
  label: string;
  value: string;
}

export interface EquityPoint {
  at: string;
  equity: string;
  drawdown_pct: string;
}

export interface LabStrategy {
  id: string;
  name: string;
  description: string;
  rules: LabRule[];
  /** True for Equal Weight v1, the permanent benchmark. Never more than one. */
  is_baseline: boolean;

  invested: string;
  /** Every trade, with open positions marked at the latest observed price. */
  total_return_pct: string | null;
  /** Closed trades only. Win rate and profit factor are closed-only too. */
  realised_return_pct: string | null;
  /** How much of the total is a mark rather than a result. */
  open_share_pct: string | null;
  baseline_difference_pct: string | null;
  annualised_return_pct: string | null;
  annualised_unavailable_reason: string | null;

  closed_count: number;
  open_count: number;
  win_rate_pct: string | null;
  profit_factor: string | null;
  average_win: string | null;
  average_loss: string | null;
  largest_winner: string | null;
  largest_loser: string | null;
  max_drawdown_pct: string | null;
  average_hold_hours: string | null;
  /** How high positions got, and how much of it was handed back. */
  average_peak_pct: string | null;
  average_giveback_pct: string | null;
  exits_by_reason: Record<string, number>;

  rank: number;
  equity_curve: EquityPoint[];
  return_distribution: string[];
  hold_distribution: string[];
}

export interface UnavailableStrategy {
  id: string;
  name: string;
  reason: string;
}

export interface LabFinding {
  headline: string;
  detail: string;
  strategy_id: string | null;
}

export interface Lab {
  strategies: LabStrategy[];
  unavailable: UnavailableStrategy[];
  findings: LabFinding[];
  baseline_id: string;
  detections: number;
  unpriced_detections: number;
  observed_days: string | null;
  /** Why a lab return is not a wallet balance. Render it. */
  methodology: string;
  observed_at: string;
}

export interface TokenComparison {
  mint_address: string;
  symbol: string | null;
  peak_pct: string | null;
  returns: Record<string, string | null>;
  best_strategy_id: string | null;
  best_capture_pct: string | null;
}

export interface LabTokens {
  items: TokenComparison[];
  strategy_ids: string[];
  observed_at: string;
}

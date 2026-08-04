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

/**
 * The Karthik wallet's API shapes.
 *
 * Money is a string everywhere, exactly as the backend sends it. Parsing it to
 * a number here would round a price of 4.8e-10 into uselessness and would put a
 * second, disagreeing copy of every figure in the client.
 *
 * `null` means *not measured*. A position with `current_price: null` has no
 * fresh quote; it does not have a price of zero, and the page must render a
 * dash for it rather than a number.
 */

export interface KarthikPosition {
  mint_address: string;
  symbol: string | null;
  token_name: string | null;

  /** The three moments, each from its own source. Null is never substituted. */
  detected_at: string | null;
  track_record_at: string;
  opened_at: string;
  track_record_delay_seconds: number | null;
  detection_delay_seconds: number | null;

  entry_price: string;
  entry_observed_price: string;
  quantity: string;
  cost_basis: string;
  decimals: number;
  target_price: string;
  target_multiple: string;

  pool_address: string | null;
  entry_liquidity_usd: string | null;
  entry_market_cap: string | null;
  entry_execution_model_version: string | null;
  entry_execution_price_impact_pct: string | null;
  entry_execution_route: string | null;
  entry_execution_confidence: string | null;
  entry_execution_fallback_reason: string | null;

  status: "open" | "closed";
  peak_price: string;
  current_price: string | null;
  current_multiple: string | null;
  current_value: string | null;
  unrealized_pnl: string | null;
  last_market_check_at: string | null;

  closed_at: string | null;
  exit_price: string | null;
  exit_observed_price: string | null;
  exit_proceeds_usd: string | null;
  exit_multiple: string | null;
  exit_reason: string | null;
  exit_execution_route: string | null;
  exit_evidence: string | null;
  realized_pnl: string | null;
  hold_seconds: number | null;
  age_seconds: number;
}

export interface KarthikSkipped {
  mint_address: string;
  track_record_at: string;
  decided_at: string;
  reason: string;
}

export interface KarthikMetrics {
  starting_capital: string;
  cash: string;
  full_equity: string;
  capital_allocated: string;
  realized_pnl: string;
  unrealized_pnl: string;
  return_pct: string;

  open_positions: number;
  closed_positions: number;
  wins: number;
  dead_zero: number;
  win_rate_pct: string | null;
  average_hold_seconds: number | null;

  track_record_opportunities: number;
  entered: number;
  skipped_insufficient_cash: number;
  skipped_no_market: number;
  capture_rate_pct: string | null;
  targets_hit: number;
  dead_zero_count: number;
  historical_backfill: number;
}

export interface KarthikWallet {
  activated: boolean;
  name: string;
  strategy: string;
  entries_paused: boolean;
  /** Why, in the server's words — shared with the paper wallet and HQ. */
  pause_reason: string;
  wallet_id: string | null;
  activated_at: string | null;
  trade_size: string | null;
  take_profit_multiple: string | null;
  metrics: KarthikMetrics | null;
  disclosure: string;
}

export interface KarthikPositions {
  items: KarthikPosition[];
}

export interface KarthikSkippedList {
  items: KarthikSkipped[];
}

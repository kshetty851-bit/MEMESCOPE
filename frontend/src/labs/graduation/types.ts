/** Shapes returned by `/labs/graduation/status`. Mirrors `api.py`. */

export interface Funnel {
  seen: number;
  crossed_70: number;
  crossed_80: number;
  crossed_90: number;
  crossed_95: number;
  graduated: number;
}

/**
 * Graduation is reported by two INDEPENDENT sources and either can arrive
 * alone, so the split is published rather than summed away.
 */
export interface Signals {
  both: number;
  feed_only: number;
  chain_only: number;
}

export interface RecentToken {
  mint: string;
  symbol: string | null;
  max_progress_pct: string | null;
  tracked: boolean;
  migrated: boolean;
  sample_count: number;
}

export interface GraduationStatus {
  running: boolean;
  rpc_host: string;
  poll_interval_s: number;
  watch_set: number;
  watch_set_max: number;
  funnel: Funnel;
  signals: Signals;
  curve_samples: number;
  checkpoints: number;
  checkpoints_with_reserves: number;
  postgrad_samples: number;
  rpc_calls_per_minute: number;
  samples_last_hour: number;
  tokens_last_hour: number;
  recent: RecentToken[];
  quote_side_trusted: boolean;
  /** The RPC's pulse. `last_sample_at` advances on every successful chain
   * read, so a stall here means the poller is not reading — a revoked key, a
   * dead node, a crashed loop — none of which a row count can show. */
  last_chain_read_at: string | null;
  seconds_since_chain_read: number | null;
  recorder_stalled: boolean;
  stall_threshold_s: number;
  paper: PaperBook;
}


export interface PaperPosition {
  /** The FULL mint address. Shown in full and linked, because a truncated
   * address cannot be pasted into an explorer and an unverifiable P&L number
   * is worth less than no number. */
  mint: string;
  symbol: string | null;
  name: string | null;
  opened_at: string;
  notional_usd: string;
  open_fill: string;
  last_quote: string | null;
  peak_quote: string;
  closed_at: string | null;
  close_reason: string | null;
  /** Realised for a closed position; marked to market for an open one. */
  pnl_usd: string | null;
  /** Likewise, so an open position shows a return rather than a dash. */
  net_return: string | null;
  /** The recorded price series for this mint crossed pools, so the trade is
   * shown and counts for nothing. */
  voided: boolean;
}

/** The forward paper book. Rules frozen in advance; nothing here is tunable. */
export interface PaperBook {
  running: boolean;
  starting_usd: string;
  equity_usd: string;
  realised_usd: string;
  unrealised_usd: string;
  pnl_usd: string;
  return_pct: string;
  open_positions: number;
  closed_positions: number;
  wins: number;
  /** Closed trades excluded from every figure above because their
   * price series crossed pools. */
  voided: number;
  max_slots: number;
  notional_usd: string;
  trailing_pct: string;
  /** Take profit as a multiple of the price paid: 2 is "sell at 2x". */
  take_profit_x: string;
  max_hold_minutes: number;
  /** The gate this run was given before it produced a trade. */
  gate_started: string;
  gate_weeks: number;
  gate_min_pf: string;
  gate_min_trades: number;
  gate_max_token_share: string;
  profit_factor: string | null;
  top_token_share: string | null;
  /** One leg's modelled cost: pump fee + assumed slippage + priority fee. */
  cost_pct_per_side: string;
  open_trades: PaperPosition[];
  closed_trades: PaperPosition[];
}

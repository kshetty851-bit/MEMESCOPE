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
  /** The lab's own resolution: of curves seen complete, how many were ever
   * seen climbing, and how many at 90%+. This bounds every pre-graduation
   * question — you can only trade what you can see. */
  graduates_observed: number;
  graduates_seen_climbing: number;
  graduates_seen_at_90: number;
  /** The RPC's pulse. `last_sample_at` advances on every successful chain
   * read, so a stall here means the poller is not reading — a revoked key, a
   * dead node, a crashed loop — none of which a row count can show. */
  last_chain_read_at: string | null;
  seconds_since_chain_read: number | null;
  recorder_stalled: boolean;
  stall_threshold_s: number;
  paper: PaperBook;
  /** The A/B twin: identical rules behind an entry filter, on the same
   * graduations. Compared against `paper` after four weeks. */
  paper_filtered: PaperBook;
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
  /** `control` or `filtered`. Same rules; the second adds one entry check. */
  book: string;
  filter_description: string;
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


/** One "reached at least this multiple" tier. Cumulative, so tiers nest. */
export interface ReturnTier {
  label: string;
  reached: number;
}

/**
 * How far each graduated token got from its pool open, and where it ended.
 * Peaks are not outcomes, so both are published together.
 */
export interface Returns {
  running: boolean;
  seen: number;
  migrated: number;
  priced: number;
  excluded_multi_pool: number;
  usable: number;
  tiers: ReturnTier[];
  ended_below_open: number;
  ended_down_90: number;
  best_multiple: string | null;
}


/** One arm's standing. Realised only — an open position is not a result. */
export interface ArmRow {
  name: string;
  note: string;
  entry: string;
  hold_minutes: number;
  take_profit_x: string | null;
  trailing_pct: string | null;
  is_control: boolean;
  trades: number;
  wins: number;
  realised_usd: string;
  mean_pct: string | null;
  profit_factor: string | null;
  top_token_share: string | null;
  open_positions: number;
}

/**
 * Fifty arms, eight of which cannot have an edge. `control_band` is the best
 * realised P&L among those eight; a leader that has not cleared it has not
 * beaten chance.
 */
export interface Leaderboard {
  running: boolean;
  started_at: string | null;
  arms: ArmRow[];
  controls: ArmRow[];
  control_band: string | null;
  best_control: string;
  leader: string;
  leader_beats_controls: boolean;
  min_trades: number;
  min_profit_factor: string;
  max_token_share: string;
  called: boolean;
  verdict: string;
  total_trades: number;
  notional_usd: string;
}

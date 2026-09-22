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
  /** What the fill was priced against — the pool's total value at each leg,
   * and the constant-product move the order caused. Published so a trade can
   * be audited against DexScreener rather than trusted. */
  liq_open_usd: string | null;
  liq_close_usd: string | null;
  impact_open: string | null;
  impact_close: string | null;
  /** What this trade made or lost for the wallet SIZE the reader picked, and
   * whether that wallet could pay for it. Null unless a size was asked for:
   * the book itself always trades $100. */
  size_pnl_usd: string | null;
  size_funded: boolean | null;
  /** Why this trade counts for nothing: `not_graduation_pool` for a token that
   * never graduated from pump.fun, `rugged` for a trade whose pool was drained
   * while it was open (left out on request). Shown struck through, never
   * summed. */
  excluded: string | null;
  /** Set on a trade rebooked by the 2026-09-16 restatement: `fees` when only
   * the fees changed, otherwise the new exit's reason (`max_hold`,
   * `pool_collapsed`, `stale_exit`). */
  restated: string | null;
  /** What the trade said before it was restated. */
  was_pnl_usd: string | null;
  was_net_return: string | null;
}

/** The forward paper book. Rules frozen in advance; nothing here is tunable. */
export interface PaperBook {
  running: boolean;
  /** Echoed back when a size was asked for. The funded trades below sum to
   * `size_end_usd - size_start_usd`, which is the row's wallet figure. */
  size_ticket_usd?: string | null;
  size_start_usd?: string | null;
  size_end_usd?: string | null;
  size_funded?: number | null;
  size_skipped?: number | null;
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
/** The funded wallet at another size: `start_usd` in `split` tickets of `ticket_usd`. */
export interface SplitWallet {
  split: number;
  ticket_usd: string;
  start_usd: string;
  wallet_usd: string;
  trades_funded: number;
  trades_skipped: number;
  /** The least the wallet held at any sell, open trades at cost. */
  low_usd: string;
}

export interface ArmRow {
  name: string;
  note: string;
  entry: string;
  /** The rule in full, in words — built from the Arm itself, so the page
   * cannot describe a strategy the tournament is not running. */
  entry_rule: string;
  exit_rule: string;
  hold_minutes: number;
  take_profit_x: string | null;
  trailing_pct: string | null;
  is_control: boolean;
  trades: number;
  wins: number;
  realised_usd: string;
  mean_pct: string | null;
  /** The token's own move per trade, before execution took its cut. */
  gross_pct: string | null;
  /** What execution took: fees plus impact. gross - net. */
  cost_pct: string | null;
  profit_factor: string | null;
  top_token_share: string | null;
  open_positions: number;
  /** Realised P&L as a percentage of the arm's $1,000. */
  return_pct: string;
  /** Capital + realised + open positions marked to their last price — what a
   * real account would show. The only figure here that includes anything not
   * yet banked. */
  equity_usd: string;
  unrealised_usd: string;
  /** What a real $100 wallet would hold, having taken these same trades. Not
   * the tournament equity divided by ten: that book is additive, while a $100
   * account is fully invested and compounds, spread over ten positions of a
   * tenth of equity each — which is what keeps it alive. */
  wallet_100_usd: string;
  /** The same $100, but only taking trades it could actually fund. */
  wallet_funded_usd: string;
  trades_funded: number;
  trades_skipped: number;
  /** The same wallet at every split the board offers; split 1 is the column
   * above. Empty for an arm with no trades. */
  splits: SplitWallet[];
  /** Hours since THIS arm's first trade, not the board clock. */
  arm_hours: string;
  /** ISO time of this arm's first position — the anchor a live clock ticks from. */
  first_trade_at: string | null;
  /** The worst single trade. The number that decides the figure above. */
  worst_trade_pct: string | null;
  /** Thirty days of the same rule at the same trade rate: median, and the
   * 5th-95th band. The band is the point — a single figure would hide how
   * little a few dozen trades actually says. */
  projected_1d_usd: string | null;
  projected_1w_usd: string | null;
  projected_15d_usd: string | null;
  projected_30d_usd: string | null;
  projected_30d_low: string | null;
  projected_30d_high: string | null;
  projected_trades: number;
  /** Share of simulated 30-day paths where the account could no longer fund a
   * position. A running total cannot express this at all. */
  ruin_pct: string | null;
  ruin_days: number;
}

/**
 * Fifty arms, eight of which cannot have an edge. `control_band` is the best
 * realised P&L among those eight; a leader that has not cleared it has not
 * beaten chance.
 */
export interface StartWalk {
  started_on: string;
  trades: number;
  rugs: number;
  balance_usd: string;
  pnl_usd: string;
  return_pct: string;
  /** The least it was ever worth — the column that decides whether a person
      would still have been holding it. */
  lowest_usd: string;
}

export interface FreshBook {
  book: string;
  hold_minutes: number;
  /** The arm's rule in words, as its board row shows it. */
  rule: string;
  started_at: string;
  capital_usd: string;
  ticket_usd: string;
  balance_usd: string;
  pnl_usd: string;
  return_pct: string;
  trades: number;
  wins: number;
  rugs: number;
  /** Signals it had no free money for. */
  skipped: number;
  lowest_usd: string;
}

/** One closed trade of a fresh book, as if it had never been sold. */
export interface HeldRow {
  mint: string;
  symbol: string | null;
  opened_at: string;
  closed_at: string | null;
  /** What the book's wallet got back selling at its exit. */
  sold_usd: string | null;
  /** The same coins never sold: what the pool pays for them now. */
  held_usd: string | null;
  /** The pool's total value now; a drained pool is why a coin is worth nothing. */
  depth_usd: string | null;
}

/** A fresh book's closed coins if nothing had been sold, read on-chain now. */
export interface FreshHeld {
  book: string;
  ticket_usd: string;
  capital_usd: string;
  read_at: string | null;
  rows: HeldRow[];
  sold_usd: string;
  held_usd: string;
  unreadable: number;
  /** A wallet that never sold could only buy its first capital / ticket trades. */
  wallet_trades: number;
  wallet_held_usd: string;
}

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
  /** The PF required of THIS leader, at its own trade count: the 95th
   * percentile of the best-of-42 profit factor when every arm is noise. */
  required_profit_factor: string;
  max_token_share: string;
  called: boolean;
  verdict: string;
  total_trades: number;
  notional_usd: string;
  capital_usd: string;
  wallet_demo_usd: string;
  wallet_demo_slots: number;
  hours_running: string;
  /** The 2026-09-16 restatement of these arms' closed trades. */
  restated_rule: string;
  restated_trades: number;
  /** Never graduations: shown on each arm's panel, counted nowhere. */
  restated_excluded: number;
  /** Exits moved to the first price recorded after they were due. */
  restated_repriced: number;
  /** Of those, exits that fell after the pool had been drained. They are
   * left out of every figure, and `restated_rugged_usd` is what they lost. */
  restated_collapsed: number;
  restated_rugged_usd: string;
  /** Closed trades the real wallet's money checks would have refused: left out
   * of every figure since 18 Sep, and what they made together. */
  blocked_trades: number;
  blocked_pnl_usd: string;
  /** Karthik's fresh books: an arm's trades from its start, walked through
   * that book's own wallet. `fresh` is the first, as before. */
  fresh: FreshBook | null;
  fresh_books: FreshBook[];
  /** One $500 wallet per start day, so a reader can see how much of a result
      is the strategy and how much is the day they happened to begin. */
  start_walks?: StartWalk[];
  rolling_book?: string;
  rolling_capital_usd?: string;
  rolling_ticket_usd?: string;
  rolling_last_day?: string | null;
}

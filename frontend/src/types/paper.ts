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
  image_url?: string | null;

  status: string;
  opened_at: string;
  /** The Radar place the token held when it was bought. */
  entry_rank: number;
  entry_price: string;
  entry_observed_price: string | null;
  size_usd: string;
  quantity: string;
  entry_execution_model_version: string | null;
  entry_execution_price_impact_pct: string | null;
  entry_execution_fee_usd: string | null;
  entry_execution_route: string | null;
  entry_execution_quoted_at: string | null;
  entry_execution_confidence: string | null;
  entry_execution_fallback_reason: string | null;
  /** The market as it stood at entry. Recorded, never used to size anything. */
  entry_market_cap: string | null;
  entry_liquidity_usd: string | null;

  /**
   * Fixed at entry, never recomputed. Null where the strategy publishes no such
   * rule — the live strategy has no target, no fixed stop and no expiry, and a
   * zero would read as a rule sitting at zero.
   */
  target_price: string | null;
  stop_price: string | null;
  expires_at: string | null;
  /** The trailing fraction fixed at entry. "0.25" is 25% back from the high. */
  trailing_drawdown: string | null;
  trailing_activation_multiple?: string | null;
  trailing_activated_at?: string | null;
  trailing_activation_observed_price?: string | null;
  trailing_high_price?: string | null;
  /** Where the trail sits now: the running high less the fixed fraction. */
  trailing_stop_price: string | null;
  trailing_trigger_price?: string | null;
  trailing_trigger_observed_price?: string | null;

  /** Null for a token nobody has priced since — unmeasured, not worthless. */
  current_price: string | null;
  current_pct: string | null;
  /** When the mark was observed. Exit time for a closed trade. */
  current_price_at: string | null;
  /** When the market was last checked, even if no observation was found. */
  last_market_check_at?: string | null;
  /** For a closed trade this stops at the exit, not at the token's later high. */
  peak_pct: string | null;

  closed_at: string | null;
  exit_price: string | null;
  exit_observed_price: string | null;
  exit_execution_model_version: string | null;
  exit_execution_price_impact_pct: string | null;
  exit_execution_fee_usd: string | null;
  exit_execution_route: string | null;
  exit_execution_quoted_at: string | null;
  exit_execution_confidence: string | null;
  exit_execution_fallback_reason: string | null;
  /** `target` | `stop` | `expiry` | `manual`. */
  exit_reason: string | null;
  manual_action_at: string | null;
  pnl_usd: string | null;
  /** Immutable figures recorded when a position closes. Null for open or
   * uncosted positions; unlike `pnl_usd`, these distinguish every cost. */
  gross_pnl_usd: string | null;
  fee_usd: string | null;
  slippage_usd: string | null;
  net_pnl_usd: string | null;
  cost_unavailable_reason: string | null;
}

export interface ManualSellPreview {
  mint_address: string;
  name: string | null;
  symbol: string | null;
  image_url?: string | null;
  short_mint: string;
  entry_price: string;
  entry_observed_price: string | null;
  latest_price: string;
  quote_observed_at: string;
  quote_age_seconds: string;
  is_stale: boolean;
  warning: string | null;
  entry_market_cap: string | null;
  current_market_cap: string | null;
  liquidity_usd: string | null;
  gross_return_usd: string;
  gross_return_pct: string;
  fee_usd: string | null;
  slippage_usd: string | null;
  net_return_usd: string | null;
  net_return_pct: string | null;
  cost_unavailable_reason: string | null;
  execution_model_version: string | null;
  exit_execution_price_impact_pct: string | null;
  exit_execution_fee_usd: string | null;
  exit_execution_route: string | null;
  exit_execution_quoted_at: string | null;
  execution_confidence: string | null;
  execution_fallback_reason: string | null;
}

export interface ManualSellResult {
  closed: boolean;
  preview: ManualSellPreview;
  audited: boolean;
  opened: number;
  candidates: number;
  candidates_truncated: boolean;
  refusals: Record<string, number>;
}

export interface PaperBenchmark {
  id: string;
  label: string;
  description: string;
  return_pct: string | null;
  difference_pct: string | null;
  unavailable_reason: string | null;
  /** How many tokens it held, and how many were unpriceable at one end. The
   * second is published rather than dropped: excluding them would hand the
   * benchmark survivorship it did not earn. */
  positions: number;
  unpriced: number;
}

/**
 * Why the wallet is idle, whenever it is.
 *
 * Two distinct states, named by `reason`:
 *  - `nothing_qualifies` — cash enough for a position, nothing on the Radar
 *    passing the entry conditions.
 *  - `cash_below_trade_size` — something may qualify, but what is left will not
 *    fund a whole position and the strategy never part-fills. A wait for a
 *    close, not for an opportunity.
 *
 * `labels` carries the server-rendered sentence for each refusal code, so the
 * client never composes prose from a slug.
 */
export interface PaperWaiting {
  reason: string;
  message: string;
  idle_cash: string;
  trade_size: string;
  /** How far short of one position. "0" when not short. */
  shortfall: string;
  considered: number;
  /** How many would be bought if the cash were there. Separates "no
   * opportunity" from "no capital". */
  eligible: number;
  refusals: Record<string, number>;
  labels: Record<string, string>;
}

export interface PaperLastTrade {
  /** `opened` or `closed`. Opens count — a fully-invested wallet still acted. */
  action: string;
  mint_address: string;
  symbol: string | null;
  image_url?: string | null;
  at: string;
  price_usd: string | null;
  exit_reason: string | null;
  pnl_usd: string | null;
}

/** One completed trade, as it was written down and never rewritten. */
export interface PaperAuditEntry {
  mint_address: string;
  symbol: string | null;
  image_url?: string | null;

  entry_at: string;
  entry_price: string;
  entry_observed_price: string | null;
  entry_market_cap: string | null;
  entry_liquidity_usd: string | null;
  size_usd: string;
  quantity: string;

  exit_at: string;
  exit_price: string;
  exit_observed_price: string | null;
  exit_market_cap: string | null;
  exit_liquidity_usd: string | null;

  gross_return_usd: string;
  gross_return_pct: string;
  /** Null together, with the reason set, when the venue reported no depth. */
  fee_usd: string | null;
  slippage_usd: string | null;
  net_return_usd: string | null;
  net_return_pct: string | null;
  cost_unavailable_reason: string | null;

  exit_reason: string;
  manual_action_at: string | null;
  strategy_id: string;
  strategy_version: string;
  wallet_generation: number;
  hold_hours: string | null;
  execution_model_version: string | null;
  entry_execution_model_version: string | null;
  exit_execution_model_version: string | null;
  entry_execution_price_impact_pct: string | null;
  exit_execution_price_impact_pct: string | null;
  entry_execution_fee_usd: string | null;
  exit_execution_fee_usd: string | null;
  entry_execution_route: string | null;
  exit_execution_route: string | null;
  entry_execution_quoted_at: string | null;
  exit_execution_quoted_at: string | null;
  execution_confidence: string | null;
  execution_fallback_reason: string | null;
}

export interface PaperAudit {
  items: PaperAuditEntry[];
  total: number;
  enabled: boolean;
  disclosure: string;
  observed_at: string;
}

/** One UTC day of completed-trade returns from the permanent record. */
export interface PaperDailyReturn {
  date: string;
  completed_trades: number;
  gross_pnl_usd: string;
  /** Daily P/L as a percentage of the wallet's starting capital. */
  gross_return_pct: string | null;
  /** Null if any completed trade that day could not be costed. */
  net_pnl_usd: string | null;
  net_return_pct: string | null;
  cost_unavailable_trades: number;
}

export interface PaperPerformance {
  enabled: boolean;
  /** Newest UTC day first. */
  daily: PaperDailyReturn[];
  disclosure: string;
  observed_at: string;
}

export interface PaperMetrics {
  starting_balance: string;
  cash: string;
  /** Null when any open holding is unpriced. */
  equity: string | null;
  roi_pct: string | null;
  /** Current marked-to-market P/L from starting capital. Null follows equity. */
  return_usd: string | null;
  open_value: string | null;
  /** Cash plus only holdings with valid current post-resume marks. */
  known_partial_equity: string;
  /** What the open holdings cost at entry. Never null: an unpriced holding has
   * an unknown value but a known cost. */
  invested_usd: string;
  unpriced_positions: number;
  priced_positions: number;

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
  /** Which launch this is, and when it began. The benchmarks start there too. */
  generation: number;
  started_at: string | null;
  /** Present when this is a preserved historical generation resumed forward. */
  resumed_at: string | null;
  last_trade: PaperLastTrade | null;
  /** The next moment the ranking can change. Exits do not wait for it. */
  next_radar_evaluation_at: string | null;
  audited_trades: number;
  /** Realised profit since midnight UTC. Realised only. */
  pnl_today: string;
  /** Rendered on every surface that shows the numbers. */
  disclosure: string;
  observed_at: string;
}

export interface PaperWalletContext {
  benchmarks: PaperBenchmark[];
  /** Set while both benchmarks hold the same tokens. */
  benchmark_note: string | null;
  waiting: PaperWaiting | null;
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

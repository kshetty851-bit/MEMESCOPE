/**
 * BTC RANGE LAB — wire types for `/labs/btc-range/*`.
 *
 * Every price and money figure is a decimal STRING, kept as a string until
 * display (see `@/lib/format`). Timestamps are ISO-8601 UTC. Paper only: no
 * route here can place an order, and nothing on the page may suggest one.
 */

export type Call = "long" | "short" | "wait";
export type Regime =
  | "range"
  | "trending"
  | "breakout_up"
  | "breakout_down"
  | "undefined";
export type ExitReason =
  | "take_profit"
  | "stop_loss"
  | "time_stop"
  | "end_of_data";

/** A stable code plus the server-rendered sentence. Never compose prose here. */
export interface ReasonOut {
  code: string;
  text: string;
}

export interface RangeOut {
  support: string;
  resistance: string;
  mid: string;
  width_pct: string;
  /** (price - support) / width. <0 or >1 is outside the range. */
  position: string;
  touches_support: number;
  touches_resistance: number;
  trend_efficiency: string;
  confidence: number;
  regime: Regime;
}

export interface SignalOut {
  at: string;
  price: string;
  call: Call;
  confidence: number;
  range: RangeOut | null;
  /** null on WAIT — never estimated. */
  entry: string | null;
  take_profit: string | null;
  stop_loss: string | null;
  reward_risk: string | null;
  reasons: ReasonOut[];
}

export interface MetricsOut {
  trades: number;
  wins: number;
  losses: number;
  /** Percent; null with no trades. */
  win_rate: string | null;
  net_pnl: string;
  gross_profit: string;
  gross_loss: string;
  /** null when there is no losing trade (undefined, not infinite). */
  profit_factor: string | null;
  expectancy: string | null;
  max_drawdown_pct: string | null;
  return_pct: string;
  ending_equity: string;
}

export interface TradeOut {
  side: "long" | "short";
  signal_at: string;
  entry_at: string;
  entry_price: string;
  take_profit: string;
  stop_loss: string;
  quantity: string;
  notional: string;
  exit_at: string;
  exit_price: string;
  exit_reason: ExitReason;
  fees: string;
  pnl: string;
  r_multiple: string | null;
}

export interface OpenPositionOut {
  side: "long" | "short";
  signal_at: string;
  entry_at: string;
  entry_price: string;
  take_profit: string;
  stop_loss: string;
  quantity: string;
  notional: string;
  mark_price: string;
  unrealised_pnl: string;
}

export interface EquityPointOut {
  at: string;
  equity: string;
}

export interface CandleOut {
  /** Candle start. */
  t: string;
  o: string;
  h: string;
  l: string;
  c: string;
}

export interface BookOut {
  started_at: string;
  config_version: number;
  /** The config this book runs on — the live calls are made with it, not with
   * whatever /config reports as today's defaults. */
  config: StrategyConfigOut;
  metrics: MetricsOut;
  long: MetricsOut;
  short: MetricsOut;
  open_position: OpenPositionOut | null;
  /** Newest first, at most 100. */
  trades: TradeOut[];
  /** Oldest first, downsampled to at most 300 points. */
  equity_curve: EquityPointOut[];
}

export interface DataOut {
  candles: number;
  first_at: string | null;
  last_closed_at: string | null;
  /** True when the newest closed candle is older than two candle periods. */
  stale: boolean;
}

export interface PriceOut {
  value: string;
  at: string;
  /** False when the price is the still-forming candle's latest close. */
  candle_closed: boolean;
}

/** GET /labs/btc-range/status */
export interface StatusOut {
  running: boolean;
  /** Set when running is false, or when data is missing. */
  reason: string | null;
  symbol: string;
  timeframe: string;
  paper_only: true;
  price: PriceOut | null;
  data: DataOut;
  signal: SignalOut | null;
  book: BookOut | null;
  /** The last 192 closed candles, oldest first, for the range chart. */
  candles: CandleOut[];
}

/** Every tunable; same names as the backend StrategyConfig. Decimals are strings. */
export interface StrategyConfigOut {
  lookback: number;
  touch_tolerance: string;
  min_touches: number;
  min_width_pct: string;
  max_width_pct: string;
  max_trend_efficiency: string;
  min_confidence: number;
  entry_zone: string;
  tp_target: string;
  sl_buffer: string;
  min_reward_risk: string;
  max_hold_candles: number;
  cooldown_candles: number;
  allow_long: boolean;
  allow_short: boolean;
  starting_balance: string;
  risk_per_trade_pct: string;
  max_leverage: string;
  fee_bps: string;
  slippage_bps: string;
}

export interface FieldBounds {
  min: string;
  max: string;
  step: string;
  label: string;
  help: string;
  /** "int" | "decimal" | "bool" */
  kind: "int" | "decimal" | "bool";
  group: "range" | "entries" | "account";
}

/** GET /labs/btc-range/config */
export interface ConfigOut {
  config_version: number;
  defaults: StrategyConfigOut;
  bounds: Record<keyof StrategyConfigOut, FieldBounds>;
  /** ISO bounds of stored candles a backtest can use. */
  data_first_at: string | null;
  data_last_at: string | null;
}

/** POST /labs/btc-range/backtest body. Omitted fields take the defaults. */
export interface BacktestIn {
  config: Partial<StrategyConfigOut>;
  /** Defaults: end = latest closed candle, start = end - 30 days. */
  start?: string;
  end?: string;
}

export interface BacktestOut {
  /** False when there are not enough stored candles for the window. */
  available: boolean;
  reason: string | null;
  config: StrategyConfigOut;
  start: string | null;
  end: string | null;
  candles: number;
  signal_counts: Record<Call, number>;
  /** Reason code → count, over WAIT calls. */
  wait_reasons: Array<ReasonOut & { count: number }>;
  metrics: MetricsOut;
  long: MetricsOut;
  short: MetricsOut;
  /** Oldest first, at most 1,000. */
  trades: TradeOut[];
  /** Oldest first, downsampled to at most 500 points. */
  equity_curve: EquityPointOut[];
}

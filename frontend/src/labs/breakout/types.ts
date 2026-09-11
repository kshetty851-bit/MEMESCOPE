/**
 * The shapes the backend actually serves.
 *
 * **The backend is the source of truth for every field name here.** These
 * mirror `app/labs/breakout/api.py`; the fixtures in `mock.ts` are built from
 * these types, so a rename on the server breaks the build rather than
 * silently rendering an empty column.
 *
 * Numbers arrive as JSON numbers, not decimal strings — the backend converts
 * with `float()` before serialising, so there is nothing to parse here.
 */

export interface BreakoutHealth {
  running: boolean;
  universe?: {
    active: number;
    inactive: number;
    max: number;
    refreshed_at: string | null;
    stale: boolean;
  };
  coverage?: Record<string, { tokens: number; complete: number; stale: number;
    bars: number; starved: number }>;
  last_run?: Record<string, { started_at: string; age_seconds: number;
    errors: string[] }>;
}

export type SetupState =
  | "PRE_BREAKOUT"
  | "WATCHING"
  | "BROKE_OUT"
  | "FAILED"
  | "NONE";

export interface ScoreComponents {
  volume: number | null;
  structure: number | null;
  position: number | null;
  compression: number | null;
  hourly: number | null;
}

export interface Setup {
  mint: string;
  symbol: string | null;
  name: string | null;
  pool: string | null;
  state: SetupState;
  score: number;
  components: ScoreComponents;
  price: number | null;
  resistance: number | null;
  /** Percent of resistance the price is BELOW it. Negative means above. */
  distance_pct: number | null;
  opened_at: string;
  first_pre_breakout_at: string | null;
  hours_open: number;
  liquidity_usd: number | null;
  volume_24h_usd: number | null;
}

export interface Cluster {
  level: number;
  touches: number;
  first: string;
  last: string;
  broken: boolean;
}

export interface Bar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number | null;
}

export interface Episode {
  id: string;
  mint: string;
  symbol: string | null;
  opened_at: string;
  first_pre_breakout_at: string | null;
  closed_at: string | null;
  close_reason: string | null;
  entry_ref_price: number | null;
  resistance_at_open: number | null;
  max_gain_pct_from_ref: number | null;
  max_loss_pct_from_ref: number | null;
  pct_at_24h: number | null;
  pct_at_72h: number | null;
  trail25_result_pct: number | null;
  outcome_gappy: boolean;
}

export interface SetupDetail {
  running: boolean;
  token: {
    mint: string;
    symbol: string | null;
    name: string | null;
    pool_address: string;
    dex: string;
    pair_created_at: string;
    liquidity_usd: number | null;
    volume_24h_usd: number | null;
    price_usd: number | null;
    fdv: number | null;
    active: boolean;
    inactive_reason: string | null;
  } | null;
  levels: {
    clusters: Cluster[];
    nearest_resistance: number | null;
    atr: number | null;
  } | null;
  latest_snapshot: {
    bar_close_time: string;
    state: SetupState;
    score: number;
    components: ScoreComponents;
    price: number | null;
    resistance: number | null;
    distance_pct: number | null;
    hourly_missing: boolean;
  } | null;
  episode: Episode | null;
  candles: { day: Bar[]; hour: Bar[] };
}

export interface EpisodePage {
  total: number;
  items: Episode[];
}

export interface SetupStats {
  running?: boolean;
  open_by_state: Record<string, number>;
  closed: { n: number; broke_out: number; failed: number; expired: number };
  outcomes: {
    n: number;
    mean_trail25_pct: number | null;
    median_trail25_pct: number | null;
    win_rate: number | null;
    by_score_decile: {
      decile: number;
      n: number;
      mean_trail25_pct: number;
      win_rate: number;
    }[];
  };
}

export interface Account {
  equity: number;
  cash: number;
  unrealised: number;
  peak_equity: number;
  drawdown_pct: number;
  halted: boolean;
  trading_enabled: boolean;
  slots: number;
  slots_used: number;
  slot_size: number;
  updated_at: string | null;
}

export interface Position {
  mint: string;
  symbol: string | null;
  qty: number;
  entry: number;
  mark: number;
  value: number;
  high_water_value: number;
  trail_stop_value: number;
  unrealised_usd: number;
  unrealised_pct: number;
  opened_at: string;
  hours_held: number;
  episode_id: string | null;
}

export interface Trade {
  id: string;
  mint: string;
  symbol: string | null;
  entry: number;
  exit: number;
  qty: number;
  slot_size: number;
  pnl_usd: number;
  pnl_pct: number;
  fees: number;
  opened_at: string;
  closed_at: string;
  exit_reason: string;
  episode_id: string | null;
}

export interface TradePage {
  total: number;
  items: Trade[];
}

export interface EquityPoint {
  t: string;
  equity: number;
  unrealised: number;
  positions: number;
}

export interface TradeStats {
  running?: boolean;
  trades: number;
  win_rate: number | null;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
  expectancy_pct: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number;
  return_pct: number;
  by_exit_reason: Record<string, { n: number; pnl_usd: number; mean_pct: number }>;
  fees_total: number;
}

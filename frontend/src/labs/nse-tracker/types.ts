/**
 * THE ROUTE SHAPES, mirrored from `backend/app/labs/nse_breakout/api.py`.
 *
 * The backend is the truth: `test_routes.py` there asserts these field names
 * explicitly, and `page.test.tsx` here renders the same shapes from `mock.ts`.
 * A rename that only happens on one side fails a test on both.
 *
 * Every number arrives already computed. Nothing in this folder recomputes a
 * score, a distance or a return — a second implementation is a second answer,
 * and the first time either changed they would disagree.
 */

/** `NONE` | `WATCH` | `NEAR` | `BREAKOUT` | `FALSE_BREAKOUT` | `FAILED` | `EXPIRED` */
export type TrackerState =
  | "NONE"
  | "WATCH"
  | "NEAR"
  | "BREAKOUT"
  | "FALSE_BREAKOUT"
  | "FAILED"
  | "EXPIRED";

export type Source = "live" | "replay";

export interface NearRow {
  symbol: string;
  name: string | null;
  state: TrackerState;
  score: number;
  close: number;
  /** Null when nothing unbroken sits above the close — an all-time high. */
  resistance: number | null;
  distance_pct: number | null;
  tightness: boolean;
  is_52w_high: boolean;
  days_in_state: number;
  turnover_20d: number | null;
  bar_date: string;
}

export interface BreakoutRow {
  symbol: string;
  breakout_date: string;
  breakout_price: number | null;
  resistance: number | null;
  volume_mult: number | null;
  /** Against the latest stored close, so it moves with the data. */
  ret_since_pct: number | null;
  max_gain_pct: number | null;
  max_drawdown_pct: number | null;
  state: TrackerState;
  live_state: TrackerState | null;
  false_breakout: boolean;
  days_since: number;
}

export interface Cluster {
  level: number;
  touches: number;
  first: string;
  last: string;
  broken: boolean;
}

export interface Candle {
  d: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  /** The bar sits across a > 30% overnight gap: a corporate action, flagged
   *  rather than corrected, because bhavcopy is unadjusted. */
  suspect: boolean;
}

export interface Episode {
  id: string;
  symbol: string;
  source: Source;
  opened: string;
  first_near_date: string | null;
  ref_price: number | null;
  resistance: number | null;
  score_at_open: number;
  max_score: number;
  breakout_date: string | null;
  breakout_price: number | null;
  volume_mult: number | null;
  days_to_breakout: number | null;
  state: TrackerState;
  closed: string | null;
  close_reason: string | null;
  ret_ref_5: number | null;
  ret_ref_10: number | null;
  ret_ref_20: number | null;
  ret_ref_40: number | null;
  ret_bo_5: number | null;
  ret_bo_10: number | null;
  ret_bo_20: number | null;
  ret_bo_40: number | null;
  mfe_20: number | null;
  mae_20: number | null;
  held_20d_pct: number | null;
  trail10_pct: number | null;
  trail10_stopped: boolean | null;
  rel_nifty_20: number | null;
  /** False while the 40-bar window is still open. Its returns are null, and
   *  null means "not measurable yet", never zero. */
  outcomes_filled: boolean;
}

export interface StockView {
  stock: {
    symbol: string;
    name: string | null;
    series: string;
    active: boolean;
    bars: number;
    turnover_20d: number | null;
    first_seen: string;
    last_seen: string;
  };
  levels: {
    clusters: Cluster[];
    nearest_resistance: number | null;
    is_52w_high: boolean;
    week52_high: number | null;
    atr: number | null;
    range_pct: number | null;
    tightness: boolean;
  } | null;
  score: {
    score: number;
    components: Record<string, number>;
    state: TrackerState;
    days_in_state: number;
    distance_pct: number | null;
    bar_date: string;
  } | null;
  episode: Episode | null;
  history: Episode[];
  candles: Candle[];
}

export interface EpisodePage {
  total: number;
  limit: number;
  offset: number;
  items: Episode[];
}

export interface SideStats {
  n: number;
  mean_ret_20: number | null;
  median_ret_20: number | null;
  win_rate_20: number | null;
  mean_mfe: number | null;
  mean_mae: number | null;
}

export interface DecileRow {
  decile: number;
  score_range: string;
  n: number;
  reached_breakout_pct: number;
  mean_ret_bo_20: number | null;
  mean_ret_ref_20: number | null;
  win_rate: number | null;
}

export interface YearRow {
  year: number;
  episodes: number;
  reached_breakout_pct: number;
  mean_ret_bo_20: number | null;
  mean_ret_ref_20: number | null;
  rel_nifty_20_mean: number | null;
}

export interface Stats {
  source: Source;
  episodes: number;
  reached_breakout_pct: number | null;
  false_breakout_pct: number | null;
  from_ref: SideStats;
  from_breakout: SideStats;
  trail10: {
    n?: number;
    mean?: number | null;
    win_rate?: number | null;
    profit_factor?: number | null;
    stopped_pct?: number | null;
  };
  rel_nifty_20_mean: number | null;
  by_score_decile: DecileRow[];
  by_year: YearRow[];
  days_to_breakout_median?: number | null;
  /** The thresholds these numbers were produced under, so a figure can never
   *  be read against the wrong rules. */
  config?: Record<string, number>;
  caveats?: string[];
}

export interface Health {
  running: boolean;
  universe?: { active: number; inactive: number; min_price_inr: number;
    min_turnover_inr: number };
  coverage?: {
    bars_required: number;
    symbols_covered: number;
    symbols_active: number;
    pct: number;
    bars_total: number;
    first_bar: string | null;
    last_bar: string | null;
  };
  bhavcopy?: {
    last_date: string | null;
    days_ok: number;
    days_missing: number;
    days_failed: number;
    target_days: number;
    failed_days: { date: string; failures: number; error: string }[];
  };
  corporate_actions?: { suspect_gap_bars: number; gap_pct: number;
    adjusted: boolean; note: string };
  nifty?: { bars: number; first: string | null; last: string | null };
  last_run?: Record<string, { started_at: string; age_seconds: number;
    days: number; rows: number; symbols: number; detail: Record<string, unknown>;
    errors: string[] }>;
}

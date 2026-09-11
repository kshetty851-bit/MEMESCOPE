/**
 * Fixtures for every route, plus the empty variants.
 *
 * Shaped from the REAL replay payload (2026-09-11: 8,484 episodes, reach rate
 * 17.5% → 70.2% across the deciles, mean 20-day return from the breakout
 * +0.09%), so mock mode shows what the page actually looks like with data in
 * it rather than a flattering invention. A fixture that only shows winners
 * teaches you to build a page that cannot render a loss.
 */

import type {
  BreakoutRow,
  Episode,
  EpisodePage,
  Health,
  NearRow,
  Stats,
  StockView,
} from "./types";

export const MOCK_NEAR: NearRow[] = [
  { symbol: "JSWINFRA", name: "JSW INFRASTRUCTURE LTD", state: "NEAR", score: 90,
    close: 342.45, resistance: 343.3, distance_pct: 0.25, tightness: true,
    is_52w_high: false, days_in_state: 3, turnover_20d: 1_284_000_000,
    bar_date: "2026-09-10" },
  { symbol: "NEULANDLAB", name: "NEULAND LABORATORIES LTD", state: "NEAR",
    score: 77, close: 23800, resistance: 23878.93, distance_pct: 0.33,
    tightness: true, is_52w_high: true, days_in_state: 1,
    turnover_20d: 862_000_000, bar_date: "2026-09-10" },
  { symbol: "GLAND", name: "GLAND PHARMA LIMITED", state: "NEAR", score: 72,
    close: 2946.9, resistance: 3039.8, distance_pct: 3.15, tightness: true,
    is_52w_high: true, days_in_state: 6, turnover_20d: 1_940_000_000,
    bar_date: "2026-09-10" },
  { symbol: "CASTROLIND", name: "CASTROL INDIA LTD", state: "WATCH", score: 68,
    close: 188.06, resistance: 199.31, distance_pct: 5.98, tightness: false,
    is_52w_high: false, days_in_state: 12, turnover_20d: 512_000_000,
    bar_date: "2026-09-10" },
  { symbol: "TAJGVK", name: "TAJGVK HOTELS & RESORTS LTD", state: "WATCH",
    score: 63, close: 342.6, resistance: 372.5, distance_pct: 8.73,
    tightness: false, is_52w_high: false, days_in_state: 2,
    turnover_20d: 88_000_000, bar_date: "2026-09-10" },
];

export const MOCK_BREAKOUTS: BreakoutRow[] = [
  { symbol: "WABAG", breakout_date: "2026-09-04", breakout_price: 2244.5,
    resistance: 2229.5, volume_mult: 2.4, ret_since_pct: 6.8, max_gain_pct: 9.1,
    max_drawdown_pct: -2.2, state: "BREAKOUT", live_state: "BREAKOUT",
    false_breakout: false, days_since: 7 },
  { symbol: "SARDAEN", breakout_date: "2026-08-28", breakout_price: 551.0,
    resistance: 542.25, volume_mult: 1.7, ret_since_pct: -4.1,
    max_gain_pct: 2.4, max_drawdown_pct: -7.8, state: "FALSE_BREAKOUT",
    live_state: "NONE", false_breakout: true, days_since: 14 },
  { symbol: "MRPL", breakout_date: "2026-08-21", breakout_price: 188.4,
    resistance: 184.26, volume_mult: 3.1, ret_since_pct: 0.4,
    max_gain_pct: 5.5, max_drawdown_pct: -6.1, state: "BREAKOUT",
    live_state: "NONE", false_breakout: false, days_since: 21 },
];

const EPISODE: Episode = {
  id: "0f0c3a1e-7f55-4a2a-9f6e-9ad2d1d0b001", symbol: "WABAG", source: "replay",
  opened: "2026-08-24", first_near_date: "2026-08-24", ref_price: 2180.0,
  resistance: 2229.5, score_at_open: 74, max_score: 88,
  breakout_date: "2026-09-04", breakout_price: 2244.5, volume_mult: 2.4,
  days_to_breakout: 9, state: "BREAKOUT", closed: null, close_reason: null,
  ret_ref_5: 1.2, ret_ref_10: 3.4, ret_ref_20: 9.9, ret_ref_40: 11.2,
  ret_bo_5: 1.1, ret_bo_10: 2.6, ret_bo_20: 6.8, ret_bo_40: 7.4,
  mfe_20: 12.4, mae_20: -2.9, held_20d_pct: 6.8, trail10_pct: 4.2,
  trail10_stopped: true, rel_nifty_20: 4.4, outcomes_filled: true,
};

export const MOCK_EPISODES: EpisodePage = {
  total: 8484, limit: 25, offset: 0,
  items: [
    EPISODE,
    { ...EPISODE, id: "…002", symbol: "SARDAEN", opened: "2026-08-14",
      first_near_date: "2026-08-14", ref_price: 528.0, resistance: 542.25,
      score_at_open: 71, max_score: 74, breakout_date: "2026-08-28",
      breakout_price: 551.0, volume_mult: 1.7, days_to_breakout: 10,
      state: "FALSE_BREAKOUT", closed: "2026-09-01",
      close_reason: "FALSE_BREAKOUT", ret_ref_5: -0.4, ret_ref_10: -1.8,
      ret_ref_20: -5.2, ret_ref_40: -3.1, ret_bo_5: -2.1, ret_bo_10: -4.4,
      ret_bo_20: -8.6, ret_bo_40: -6.2, mfe_20: 3.1, mae_20: -9.4,
      held_20d_pct: -8.6, trail10_pct: -10.0, trail10_stopped: true,
      rel_nifty_20: -6.9 },
    // Opened inside the window: every return is null, and the page must draw
    // that as "not measurable yet" rather than as a flat trade.
    { ...EPISODE, id: "…003", symbol: "GLAND", opened: "2026-09-05",
      first_near_date: "2026-09-05", ref_price: 2946.9, resistance: 3039.8,
      score_at_open: 72, max_score: 72, breakout_date: null,
      breakout_price: null, volume_mult: null, days_to_breakout: null,
      state: "NEAR", closed: null, close_reason: null,
      ret_ref_5: null, ret_ref_10: null, ret_ref_20: null, ret_ref_40: null,
      ret_bo_5: null, ret_bo_10: null, ret_bo_20: null, ret_bo_40: null,
      mfe_20: null, mae_20: null, held_20d_pct: null, trail10_pct: null,
      trail10_stopped: null, rel_nifty_20: null, outcomes_filled: false },
  ],
};

function candles(): StockView["candles"] {
  const out: StockView["candles"] = [];
  let price = 1980;
  for (let i = 0; i < 120; i += 1) {
    const drift = i < 90 ? 1.6 : 6.5;
    price += Math.sin(i / 6) * 12 + drift;
    const open = price - 6;
    out.push({
      // Ends on the real last bar (2026-09-10) so the fixture's breakout date
      // falls INSIDE the window — a marker cannot be placed on a bar the
      // chart was not given.
      d: new Date(Date.UTC(2026, 4, 14) + i * 86_400_000).toISOString().slice(0, 10),
      o: Number(open.toFixed(2)), h: Number((price + 14).toFixed(2)),
      l: Number((price - 16).toFixed(2)), c: Number(price.toFixed(2)),
      v: 120_000 + (i % 7) * 30_000, suspect: false,
    });
  }
  return out;
}

export const MOCK_STOCK: StockView = {
  stock: { symbol: "WABAG", name: "VA TECH WABAG LTD", series: "EQ",
    active: true, bars: 608, turnover_20d: 640_000_000,
    first_seen: "2024-03-26", last_seen: "2026-09-10" },
  levels: {
    clusters: [
      { level: 1985.4, touches: 4, first: "2025-11-04", last: "2026-02-12",
        broken: true },
      { level: 2229.5, touches: 3, first: "2026-05-19", last: "2026-08-11",
        broken: false },
      { level: 2480.0, touches: 2, first: "2026-01-08", last: "2026-03-03",
        broken: false },
    ],
    nearest_resistance: 2229.5, is_52w_high: false, week52_high: 2480.0,
    atr: 48.2, range_pct: 9.4, tightness: true,
  },
  score: { score: 88, components: { proximity: 0.92, compression: 0.78,
    trend: 0.66, volume: 0.81, touches: 0.67 }, state: "BREAKOUT",
    days_in_state: 7, distance_pct: -0.7, bar_date: "2026-09-10" },
  episode: EPISODE,
  history: MOCK_EPISODES.items,
  candles: candles(),
};

export const MOCK_STATS: Stats = {
  source: "replay", episodes: 8484, reached_breakout_pct: 30.0,
  false_breakout_pct: 45.3,
  from_ref: { n: 7281, mean_ret_20: -0.0657, median_ret_20: -1.1256,
    win_rate_20: 44.97, mean_mfe: 8.8795, mean_mae: -7.6063 },
  from_breakout: { n: 2162, mean_ret_20: 0.0874, median_ret_20: -1.079,
    win_rate_20: 44.91, mean_mfe: 9.8359, mean_mae: -8.3724 },
  trail10: { n: 2162, mean: -0.2613, win_rate: 34.46, profit_factor: 0.9337,
    stopped_pct: 93.02 },
  rel_nifty_20_mean: -0.03,
  by_score_decile: [
    { decile: 7, score_range: "60-69", n: 4612, reached_breakout_pct: 17.45,
      mean_ret_bo_20: -0.312, mean_ret_ref_20: -1.0335, win_rate: 39.25 },
    { decile: 8, score_range: "70-79", n: 2652, reached_breakout_pct: 38.24,
      mean_ret_bo_20: -0.2456, mean_ret_ref_20: 0.2706, win_rate: 44.99 },
    { decile: 9, score_range: "80-89", n: 1079, reached_breakout_pct: 58.11,
      mean_ret_bo_20: 1.2156, mean_ret_ref_20: 2.782, win_rate: 50.47 },
    { decile: 10, score_range: "90-99", n: 141, reached_breakout_pct: 70.21,
      mean_ret_bo_20: -0.4531, mean_ret_ref_20: 4.6522, win_rate: 56.58 },
  ],
  by_year: [
    { year: 2025, episodes: 4495, reached_breakout_pct: 28.88,
      mean_ret_bo_20: -0.4359, mean_ret_ref_20: -0.6174,
      rel_nifty_20_mean: -1.0521 },
    { year: 2026, episodes: 3989, reached_breakout_pct: 31.26,
      mean_ret_bo_20: 0.8736, mean_ret_ref_20: 0.8244,
      rel_nifty_20_mean: 1.6191 },
  ],
  days_to_breakout_median: 3,
  config: { watch_score: 60, watch_pct: 10, near_score: 70, near_pct: 4,
    break_confirm_pct: 1, break_vol_mult: 1.5, false_window_days: 5,
    fail_pct: 8, max_episode_days: 60, trail_pct: 10 },
  caveats: [
    "survivorship: delisted names are absent from the universe, so the replay cannot see setups that ended in delisting",
    "the score's thresholds were fixed before this replay ran and were not adjusted afterwards",
    "bhavcopy is unadjusted; bars across a corporate action are flagged suspect_gap, not corrected",
  ],
};

/** The live side on day one: episodes open, no window closed yet. */
export const MOCK_STATS_LIVE: Stats = {
  ...MOCK_STATS, source: "live", episodes: 122, reached_breakout_pct: 0,
  false_breakout_pct: null,
  from_ref: { n: 0, mean_ret_20: null, median_ret_20: null, win_rate_20: null,
    mean_mfe: null, mean_mae: null },
  from_breakout: { n: 0, mean_ret_20: null, median_ret_20: null,
    win_rate_20: null, mean_mfe: null, mean_mae: null },
  trail10: { n: 0, mean: null, win_rate: null, profit_factor: null,
    stopped_pct: null },
  rel_nifty_20_mean: null, by_score_decile: [], by_year: [],
  days_to_breakout_median: null,
};

export const MOCK_HEALTH: Health = {
  running: true,
  universe: { active: 1498, inactive: 1409, min_price_inr: 20,
    min_turnover_inr: 10_000_000 },
  coverage: { bars_required: 250, symbols_covered: 1396, symbols_active: 1498,
    pct: 93.19, bars_total: 1_449_471, first_bar: "2024-03-26",
    last_bar: "2026-09-10" },
  bhavcopy: { last_date: "2026-09-10", days_ok: 608, days_missing: 37,
    days_failed: 0, target_days: 900, failed_days: [] },
  corporate_actions: { suspect_gap_bars: 425, gap_pct: 30, adjusted: false,
    note: "bhavcopy is unadjusted and no corroboration source is reachable; gaps are flagged, never corrected" },
  nifty: { bars: 608, first: "2024-03-26", last: "2026-09-10" },
  last_run: {},
};

/** Day one, before the first ingest. Every panel must render this. */
export const EMPTY_HEALTH: Health = { running: false };
export const EMPTY_NEAR: NearRow[] = [];
export const EMPTY_BREAKOUTS: BreakoutRow[] = [];
export const EMPTY_EPISODES: EpisodePage = { total: 0, limit: 25, offset: 0,
  items: [] };
export const EMPTY_STATS: Stats = {
  source: "replay", episodes: 0, reached_breakout_pct: null,
  false_breakout_pct: null,
  from_ref: { n: 0, mean_ret_20: null, median_ret_20: null, win_rate_20: null,
    mean_mfe: null, mean_mae: null },
  from_breakout: { n: 0, mean_ret_20: null, median_ret_20: null,
    win_rate_20: null, mean_mfe: null, mean_mae: null },
  trail10: {}, rel_nifty_20_mean: null, by_score_decile: [], by_year: [],
};

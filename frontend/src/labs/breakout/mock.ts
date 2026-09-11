import type {
  Account,
  BreakoutHealth,
  EpisodePage,
  EquityPoint,
  Position,
  Setup,
  SetupDetail,
  SetupStats,
  TradePage,
  TradeStats,
} from "./types";

/**
 * Fixtures for mock mode, typed against `types.ts` — which mirrors the
 * backend's own response models. That is the whole point of typing them: a
 * field renamed on the server fails this file at build time instead of
 * rendering a blank column nobody notices for a week.
 *
 * The numbers are deliberately ordinary rather than flattering. A fixture
 * where every trade wins teaches the eye to expect a page that never happens.
 */

const NOW = Date.parse("2026-09-11T12:00:00Z");
const iso = (hoursAgo: number) => new Date(NOW - hoursAgo * 3_600_000).toISOString();

/** A plausible hourly series: a rally into resistance, then a stall. */
function hourly(count: number, start: number, end: number) {
  return Array.from({ length: count }, (_, i) => {
    const t = i / (count - 1);
    const base = start + (end - start) * t;
    const wobble = Math.sin(i * 1.7) * base * 0.012;
    const close = base + wobble;
    const open = base + Math.sin((i - 1) * 1.7) * base * 0.012;
    return {
      t: iso(count - i),
      o: Number(open.toFixed(8)),
      h: Number(Math.max(open, close) * 1.008).toFixed(8) as unknown as number,
      l: Number(Math.min(open, close) * 0.992),
      c: Number(close.toFixed(8)),
      v: 12_000 + i * 140,
    };
  }).map((bar) => ({ ...bar, h: Number(bar.h) }));
}

function daily(count: number) {
  return Array.from({ length: count }, (_, i) => {
    const base = 0.0038 + Math.sin(i / 6) * 0.0004 + i * 0.000004;
    const close = base * (1 + Math.sin(i * 2.3) * 0.02);
    return {
      t: new Date(NOW - (count - i) * 86_400_000).toISOString(),
      o: Number(base.toFixed(8)),
      h: Number((Math.max(base, close) * 1.03).toFixed(8)),
      l: Number((Math.min(base, close) * 0.96).toFixed(8)),
      c: Number(close.toFixed(8)),
      v: 180_000 + i * 900,
    };
  });
}

export const MOCK_HEALTH: BreakoutHealth = {
  running: true,
  universe: { active: 41, inactive: 6, max: 300, refreshed_at: iso(0.2), stale: false },
  coverage: {
    day: { tokens: 41, complete: 33, stale: 2, bars: 6_940, starved: 2 },
    hour: { tokens: 41, complete: 28, stale: 0, bars: 12_100, starved: 0 },
  },
  last_run: {
    universe: { started_at: iso(0.2), age_seconds: 720, errors: [] },
    candles: { started_at: iso(0.2), age_seconds: 700, errors: [] },
  },
};

export const MOCK_SETUPS: Setup[] = [
  {
    mint: "AMjzRn1TBQwQfNAjHFeBb7uGbbqbJB7FzXAnGgdFPk6K",
    symbol: "SOLCEX", name: "SolCex", pool: "4Ro3pG1XZgSJENfgCccNgQqrHYVqhHjwcL27oHmXMMTG",
    state: "PRE_BREAKOUT", score: 74,
    components: { volume: 1, structure: 1, position: 0.82, compression: 0.31, hourly: 0.75 },
    price: 0.00429682, resistance: 0.00434333, distance_pct: 1.07,
    opened_at: iso(31), first_pre_breakout_at: iso(4), hours_open: 31,
    liquidity_usd: 381_989, volume_24h_usd: 262_585,
  },
  {
    mint: "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump",
    symbol: "GORK", name: "Gork", pool: "8QKJHcXiVfo7jY9mY8kpoZgJMG4F9JM2mPY243VALjMB",
    state: "WATCHING", score: 68,
    components: { volume: 0.71, structure: 0.67, position: 0.74, compression: 0.55, hourly: 0.5 },
    price: 0.0139, resistance: 0.0152, distance_pct: 8.55,
    opened_at: iso(12), first_pre_breakout_at: null, hours_open: 12,
    liquidity_usd: 128_400, volume_24h_usd: 903_220,
  },
  {
    mint: "CWZ6BsdnjkDVTGkmL6bGbJXXig6ceef12KvyGQW14cMt",
    symbol: "MOODENG", name: "Moo Deng", pool: "54Vp27uLaw4wNLo5n7r4fcC6zLamoQc28xBARjss4EUJ",
    state: "WATCHING", score: 52,
    components: { volume: 0.4, structure: 0.33, position: 0.61, compression: 0.72, hourly: null },
    price: 0.191, resistance: 0.214, distance_pct: 10.75,
    opened_at: iso(63), first_pre_breakout_at: null, hours_open: 63,
    liquidity_usd: 2_140_000, volume_24h_usd: 4_820_000,
  },
];

export const MOCK_DETAIL: SetupDetail = {
  running: true,
  token: {
    mint: MOCK_SETUPS[0]!.mint, symbol: "SOLCEX", name: "SolCex",
    pool_address: "4Ro3pG1XZgSJENfgCccNgQqrHYVqhHjwcL27oHmXMMTG", dex: "raydium",
    pair_created_at: new Date(NOW - 141 * 86_400_000).toISOString(),
    liquidity_usd: 381_989, volume_24h_usd: 262_585, price_usd: 0.00429682,
    fdv: 4_296_820, active: true, inactive_reason: null,
  },
  levels: {
    clusters: [
      { level: 0.00341, touches: 4, first: iso(2400), last: iso(1100), broken: true },
      { level: 0.00398, touches: 2, first: iso(900), last: iso(620), broken: true },
      { level: 0.00434333, touches: 5, first: iso(700), last: iso(190), broken: false },
      { level: 0.00512, touches: 3, first: iso(1900), last: iso(1500), broken: false },
    ],
    nearest_resistance: 0.00434333, atr: 0.00021,
  },
  latest_snapshot: {
    bar_close_time: iso(1), state: "PRE_BREAKOUT", score: 74,
    components: { volume: 1, structure: 1, position: 0.82, compression: 0.31, hourly: 0.75 },
    price: 0.00429682, resistance: 0.00434333, distance_pct: 1.07,
    hourly_missing: false,
  },
  episode: {
    id: "ep-1", mint: MOCK_SETUPS[0]!.mint, symbol: "SOLCEX",
    opened_at: iso(31), first_pre_breakout_at: iso(4), closed_at: null,
    close_reason: null, entry_ref_price: 0.00421, resistance_at_open: 0.00434333,
    max_gain_pct_from_ref: null, max_loss_pct_from_ref: null, pct_at_24h: null,
    pct_at_72h: null, trail25_result_pct: null, outcome_gappy: false,
  },
  candles: { day: daily(120), hour: hourly(96, 0.00381, 0.00429682) },
};

export const MOCK_EPISODES: EpisodePage = {
  total: 4,
  items: [
    {
      id: "ep-9", mint: "So1", symbol: "PNUT", opened_at: iso(190),
      first_pre_breakout_at: iso(186), closed_at: iso(150), close_reason: "BROKE_OUT",
      entry_ref_price: 0.24, resistance_at_open: 0.25, max_gain_pct_from_ref: 41.2,
      max_loss_pct_from_ref: -6.1, pct_at_24h: 18.4, pct_at_72h: 9.7,
      trail25_result_pct: 16.3, outcome_gappy: false,
    },
    {
      id: "ep-8", mint: "So2", symbol: "BONK", opened_at: iso(240),
      first_pre_breakout_at: iso(236), closed_at: iso(205), close_reason: "FAILED",
      entry_ref_price: 0.0000191, resistance_at_open: 0.0000203,
      max_gain_pct_from_ref: 3.2, max_loss_pct_from_ref: -28.7, pct_at_24h: -19.2,
      pct_at_72h: -24.0, trail25_result_pct: -25.0, outcome_gappy: false,
    },
    {
      id: "ep-7", mint: "So3", symbol: "WIF", opened_at: iso(340),
      first_pre_breakout_at: null, closed_at: iso(172), close_reason: "EXPIRED",
      entry_ref_price: null, resistance_at_open: 1.21, max_gain_pct_from_ref: null,
      max_loss_pct_from_ref: null, pct_at_24h: null, pct_at_72h: null,
      trail25_result_pct: null, outcome_gappy: false,
    },
    {
      id: "ep-6", mint: "So4", symbol: "POPCAT", opened_at: iso(410),
      first_pre_breakout_at: iso(402), closed_at: iso(390), close_reason: "FAILED",
      entry_ref_price: 0.41, resistance_at_open: 0.44, max_gain_pct_from_ref: 1.1,
      max_loss_pct_from_ref: -31.0, pct_at_24h: -22.5, pct_at_72h: -30.1,
      trail25_result_pct: -25.0, outcome_gappy: true,
    },
  ],
};

export const MOCK_STATS: SetupStats = {
  open_by_state: { PRE_BREAKOUT: 1, WATCHING: 2 },
  closed: { n: 4, broke_out: 1, failed: 2, expired: 1 },
  outcomes: {
    n: 3, mean_trail25_pct: -11.23, median_trail25_pct: -25.0, win_rate: 0.3333,
    by_score_decile: [
      { decile: 5, n: 1, mean_trail25_pct: -25.0, win_rate: 0 },
      { decile: 6, n: 1, mean_trail25_pct: -25.0, win_rate: 0 },
      { decile: 7, n: 1, mean_trail25_pct: 16.3, win_rate: 1 },
    ],
  },
};

export const MOCK_ACCOUNT: Account = {
  equity: 963.41, cash: 763.02, unrealised: -12.7, peak_equity: 1_021.8,
  drawdown_pct: 5.72, halted: false, trading_enabled: true, slots: 10,
  slots_used: 2, slot_size: 96.34, updated_at: iso(0.1),
};

export const MOCK_ACCOUNT_HALTED: Account = {
  ...MOCK_ACCOUNT, equity: 588.2, drawdown_pct: 42.4, halted: true,
  slots_used: 0, slot_size: 58.82,
};

export const MOCK_ACCOUNT_EMPTY: Account = {
  equity: 1_000, cash: 1_000, unrealised: 0, peak_equity: 1_000, drawdown_pct: 0,
  halted: false, trading_enabled: false, slots: 10, slots_used: 0, slot_size: 100,
  updated_at: null,
};

export const MOCK_POSITIONS: Position[] = [
  {
    mint: MOCK_SETUPS[0]!.mint, symbol: "SOLCEX", qty: 23_301.2, entry: 0.00421,
    mark: 0.00429682, value: 100.12, high_water_value: 108.4,
    trail_stop_value: 84.32, unrealised_usd: 2.02, unrealised_pct: 2.06,
    opened_at: iso(4), hours_held: 4, episode_id: "ep-1",
  },
  {
    mint: "So5", symbol: "GIGA", qty: 412.9, entry: 0.2411, mark: 0.2168,
    value: 89.52, high_water_value: 101.3, trail_stop_value: 77.26,
    unrealised_usd: -10.04, unrealised_pct: -10.08, opened_at: iso(19),
    hours_held: 19, episode_id: "ep-2",
  },
];

export const MOCK_TRADES: TradePage = {
  total: 3,
  items: [
    {
      id: "t-3", mint: "So1", symbol: "PNUT", entry: 0.2412, exit: 0.2801, qty: 414.6,
      slot_size: 100, pnl_usd: 13.52, pnl_pct: 13.52, fees: 0.61, opened_at: iso(186),
      closed_at: iso(150), exit_reason: "trail_stop", episode_id: "ep-9",
    },
    {
      id: "t-2", mint: "So2", symbol: "BONK", entry: 0.0000193, exit: 0.0000145,
      qty: 5_181_347, slot_size: 100, pnl_usd: -25.4, pnl_pct: -25.4, fees: 0.56,
      opened_at: iso(236), closed_at: iso(205), exit_reason: "trail_stop",
      episode_id: "ep-8",
    },
    {
      id: "t-1", mint: "So4", symbol: "POPCAT", entry: 0.4141, exit: 0.3702,
      qty: 241.5, slot_size: 100, pnl_usd: -11.2, pnl_pct: -11.2, fees: 0.58,
      opened_at: iso(402), closed_at: iso(390), exit_reason: "failed_setup",
      episode_id: "ep-6",
    },
  ],
};

export const MOCK_EQUITY: EquityPoint[] = Array.from({ length: 72 }, (_, i) => ({
  t: iso(72 - i),
  equity: Number((1_000 + Math.sin(i / 9) * 34 - i * 0.5).toFixed(2)),
  unrealised: Number((Math.sin(i / 5) * 9).toFixed(2)),
  positions: i % 4 === 0 ? 1 : 2,
}));

export const MOCK_TRADE_STATS: TradeStats = {
  trades: 3, win_rate: 0.3333, avg_win_pct: 13.52, avg_loss_pct: -18.3,
  expectancy_pct: -7.69, profit_factor: 0.37, max_drawdown_pct: 8.14,
  return_pct: -3.66,
  by_exit_reason: {
    trail_stop: { n: 2, pnl_usd: -11.88, mean_pct: -5.94 },
    failed_setup: { n: 1, pnl_usd: -11.2, mean_pct: -11.2 },
  },
  fees_total: 1.75,
};

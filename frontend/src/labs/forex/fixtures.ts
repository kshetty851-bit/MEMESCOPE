import type {
  BacktestResult,
  CompareResult,
  ConfigJson,
  DataOut,
  ImportBatch,
  MetaOut,
  MetricsOut,
  QualityReport,
  ResearchResult,
  RunDetail,
  RunOut,
  Scorecard,
  StrategyMeta,
  TargetReport,
  TradeOut,
} from "./types";

/** Contract-shaped fixtures. Money is a string everywhere the contract says so. */

export const DISCLAIMER = {
  code: "target_disclaimer",
  text: "Historical observation, not a forecast. Position size is never increased to reach a target.",
};

export const config = (over: Partial<ConfigJson> = {}): ConfigJson => ({
  strategy: "london_breakout",
  symbol: "EURUSD",
  timeframe: "5m",
  direction: "both",
  params: {
    atr_period: 14,
    risk_reward: 2,
    stop_method: "atr",
    take_profit_method: "r_multiple",
    trading_session: { start_hour: 7, end_hour: 10, start_minute: 0, end_minute: 0 },
  },
  costs: {
    spread_pips: 1,
    slippage_pips: 0.2,
    commission_per_lot_side: "3.50",
    swap_long_per_lot: "-7.00",
    swap_short_per_lot: "2.00",
    financing_enabled: true,
  },
  risk: {
    initial_capital: "1000",
    max_leverage: 20,
    risk_per_trade_pct: "0.5",
    max_daily_loss_pct: "3",
    max_trades_per_day: 3,
    max_open_positions: 1,
    margin_closeout_pct: "50",
  },
  session_filter: null,
  ...over,
});

const strategy = (
  id: string,
  name: string,
  over: Partial<ConfigJson> = {},
): StrategyMeta => ({
  id,
  name,
  description: `${name} on stored candles.`,
  timeframe: "5m",
  default_config: config({ strategy: id, ...over }),
  param_fields: [
    {
      path: "params.atr_period",
      label: "ATR period",
      kind: "int",
      min: 2,
      max: 500,
      step: 1,
      help: "Bars in the ATR.",
    },
    {
      path: "params.risk_reward",
      label: "Reward to risk",
      kind: "float",
      min: 0.25,
      max: 10,
      step: 0.25,
      help: "Target as a multiple of the stop.",
    },
    {
      path: "params.stop_method",
      label: "Stop method",
      kind: "enum",
      options: ["atr", "fixed_pips", "range"],
      help: "",
    },
  ],
  default_grid: { "params.risk_reward": [1.5, 2, 3] },
});

export const meta = (): MetaOut => ({
  instruments: [
    {
      symbol: "EURUSD",
      base: "EUR",
      quote: "USD",
      pip_size: 0.0001,
      price_decimals: 5,
      contract_size: 100000,
      min_units: 1000,
      enabled: true,
    },
    {
      symbol: "GBPUSD",
      base: "GBP",
      quote: "USD",
      pip_size: 0.0001,
      price_decimals: 5,
      contract_size: 100000,
      min_units: 1000,
      enabled: false,
    },
  ],
  timeframes: ["1m", "5m", "15m", "1h"],
  risk_options_pct: ["0.25", "0.5", "1", "2"],
  strategies: [
    strategy("london_breakout", "London breakout"),
    strategy("rsi_pullback", "RSI pullback"),
    strategy("bollinger_reversion", "Bollinger reversion"),
  ],
  shared_fields: [
    { path: "symbol", label: "Instrument", kind: "enum", help: "" },
    { path: "timeframe", label: "Timeframe", kind: "enum", help: "" },
    {
      path: "direction",
      label: "Direction",
      kind: "enum",
      options: ["both", "long_only", "short_only"],
      help: "",
    },
    {
      path: "session_filter",
      label: "Entry session filter",
      kind: "session",
      help: "Blank allows any time.",
    },
    {
      path: "risk.risk_per_trade_pct",
      label: "Risk per trade (%)",
      kind: "decimal",
      help: "",
    },
    {
      path: "risk.initial_capital",
      label: "Capital (USD)",
      kind: "decimal",
      min: 100,
      max: 10000000,
      help: "",
    },
    {
      path: "risk.max_leverage",
      label: "Max leverage",
      kind: "int",
      min: 1,
      max: 20,
      help: "At most 20.",
    },
    {
      path: "risk.max_daily_loss_pct",
      label: "Daily loss limit (%)",
      kind: "decimal",
      help: "",
    },
    {
      path: "risk.max_trades_per_day",
      label: "Trades per day",
      kind: "int",
      min: 1,
      max: 50,
      help: "",
    },
    {
      path: "costs.spread_pips",
      label: "Spread (pips)",
      kind: "float",
      min: 0,
      max: 20,
      help: "",
    },
    {
      path: "costs.slippage_pips",
      label: "Slippage (pips)",
      kind: "float",
      min: 0,
      max: 20,
      help: "",
    },
    {
      path: "costs.commission_per_lot_side",
      label: "Commission per lot per side",
      kind: "decimal",
      help: "",
    },
    { path: "costs.financing_enabled", label: "Financing", kind: "bool", help: "" },
  ],
  providers: [
    {
      id: "dukascopy",
      name: "Dukascopy",
      free: true,
      needs_key: false,
      notes: "Free historical ticks, no key needed.",
      url: "https://www.dukascopy.com",
    },
    {
      id: "csv",
      name: "CSV import",
      free: true,
      needs_key: false,
      notes: "HistData and MetaTrader exports.",
    },
  ],
  target_pcts: [5, 10, 20, 50, 100],
  disclaimer: DISCLAIMER,
});

export const quality = (over: Partial<QualityReport> = {}): QualityReport => ({
  symbol: "EURUSD",
  timeframe: "5m",
  bars: 74000,
  start: "2025-01-01T00:00:00Z",
  end: "2025-12-31T00:00:00Z",
  duplicates: 0,
  misaligned: 0,
  non_utc: 0,
  ohlc_violations: 2,
  out_of_order: 0,
  expected_bars: 74500,
  missing_bars: 500,
  coverage_pct: 99.33,
  gap_count: 1,
  largest_gap_bars: 480,
  grade: "B",
  gaps: [
    {
      start: "2025-03-05T10:00:00Z",
      end: "2025-03-05T14:00:00Z",
      missing_bars: 48,
      kind: "intraday",
    },
  ],
  notes: [
    { code: "weekend_gaps_ignored", text: "Weekend closures are not counted as gaps." },
  ],
  derived_from: "stored",
  ...over,
});

export const dataOut = (): DataOut => ({
  datasets: [
    {
      symbol: "EURUSD",
      timeframe: "5m",
      bars: 74000,
      start: "2025-01-01T00:00:00Z",
      end: "2025-12-31T00:00:00Z",
      sources: ["dukascopy", "csv"],
    },
  ],
  imports: [],
  fetch: {
    provider: "dukascopy",
    days_ok: 250,
    days_empty: 5,
    days_failed: 0,
    first_day: "2025-01-01",
    last_day: "2025-12-31",
  },
  providers: meta().providers,
});

const trade = (id: number, net: string, over: Partial<TradeOut> = {}): TradeOut => {
  const loss = net.startsWith("-");
  return {
    id,
    direction: id % 2 ? "long" : "short",
    signal_time: "2025-03-03T07:10:00Z",
    entry_time: `2025-03-0${id}T07:15:00Z`,
    exit_time: `2025-03-0${id}T09:45:00Z`,
    entry_price: 1.0852,
    exit_price: loss ? 1.0841 : 1.0874,
    stop_price: 1.0841,
    take_profit_price: 1.0874,
    units: 4000,
    risk_usd: "5.00",
    gross_pnl: loss ? "-4.40" : "8.80",
    commission: "0.28",
    spread_slippage_cost: "0.52",
    financing: "0.00",
    net_pnl: net,
    r_multiple: loss ? -1.1 : 1.6,
    exit_reason: loss ? "stop_loss" : "take_profit",
    reason: "asian_high_breakout",
    ambiguous_exit: false,
    duration_minutes: 150,
    ...over,
  };
};

export const trades = (): TradeOut[] => [
  trade(1, "7.20"),
  trade(2, "-5.20"),
  trade(3, "7.20"),
  ...Array.from({ length: 27 }, (_, i) =>
    trade(i + 4, i % 3 === 0 ? "-5.20" : "7.20", {
      entry_time: `2025-04-${String((i % 27) + 1).padStart(2, "0")}T07:15:00Z`,
      exit_time: `2025-04-${String((i % 27) + 1).padStart(2, "0")}T09:45:00Z`,
    }),
  ),
];

export const metrics = (over: Partial<MetricsOut> = {}): MetricsOut => ({
  starting_balance: "1000.00",
  ending_balance: "1062.40",
  net_profit: "62.40",
  net_return_pct: 6.24,
  total_trades: 30,
  wins: 18,
  losses: 11,
  breakeven: 1,
  win_rate_pct: 60,
  avg_win: "7.20",
  avg_loss: "-5.20",
  largest_win: "9.10",
  largest_loss: "-6.30",
  gross_profit: "129.60",
  gross_loss: "-57.20",
  profit_factor: 2.27,
  expectancy_usd: "2.08",
  expectancy_r: 0.31,
  max_drawdown_pct: 3.4,
  max_drawdown_usd: "34.00",
  sharpe: null,
  sortino: null,
  sharpe_note: {
    code: "too_few_daily_returns",
    text: "Fewer than 30 daily returns, so a ratio would not be meaningful.",
  },
  longest_win_streak: 6,
  longest_loss_streak: 3,
  long_trades: 16,
  short_trades: 14,
  long_net: "40.00",
  short_net: "22.40",
  long_win_rate: 62.5,
  short_win_rate: 57.1,
  long_expectancy_r: 0.35,
  short_expectancy_r: 0.26,
  total_commission: "8.40",
  total_spread_slippage: "15.60",
  total_financing: "-1.20",
  costs_pct_of_gross_profit: 18.5,
  max_margin_utilization_pct: 12.4,
  avg_margin_utilization_pct: 3.1,
  avg_trade_duration_minutes: 150,
  monthly_trade_frequency: 5.2,
  exits_ambiguous: 1,
  margin_closeouts: 0,
  expectancy_t_stat: 1.4,
  significance_note: {
    code: "not_significant",
    text: "The expectancy is not statistically distinguishable from zero.",
  },
  ...over,
});

export const targets = (): TargetReport => ({
  months: 12,
  rows: [5, 10, 20, 50, 100].map((t, i) => ({
    target_pct: t,
    months_hit: [4, 2, 1, 0, 0][i],
    hit_rate_pct: [33.3, 16.7, 8.3, 0, 0][i],
    simulated_rate_pct: [30.1, 14.2, 6.0, 0.4, 0][i],
  })),
  profitable_months: 8,
  losing_months: 4,
  best_month: { month: "2025-06", return_pct: 7.4 },
  worst_month: { month: "2025-09", return_pct: -3.8 },
  max_drawdown_pct: 3.4,
  risk_of_ruin: {
    pct: 0.2,
    assumptions: [
      {
        code: "iid_trades",
        text: "Trades are treated as independent draws from the observed results.",
      },
    ],
  },
});

const equity = () =>
  Array.from({ length: 30 }, (_, i) => ({
    t: `2025-03-${String(i + 1).padStart(2, "0")}T21:00:00Z`,
    balance: (1000 + i * 2).toFixed(2),
    equity: (1000 + i * 2 + (i % 4 === 0 ? -6 : 1)).toFixed(2),
    margin_pct: 2.5,
  }));

export const backtestResult = (over: Partial<BacktestResult> = {}): BacktestResult => ({
  type: "backtest",
  data: {
    symbol: "EURUSD",
    timeframe: "5m",
    start: "2025-01-01T00:00:00Z",
    end: "2025-12-31T00:00:00Z",
    bars: 74000,
    sources: ["dukascopy"],
    quality_grade: "B",
    coverage_pct: 99.3,
    lower_tf_available: false,
    htf_derived: "resampled",
  },
  metrics: metrics(),
  months: [
    { month: "2025-01", return_pct: 2.1, trades: 5 },
    { month: "2025-02", return_pct: -1.4, trades: 4 },
    { month: "2025-03", return_pct: 3.3, trades: 6 },
  ],
  equity_curve: equity(),
  drawdown: equity().map((p, i) => ({ t: p.t, dd_pct: i % 4 === 0 ? -0.6 : 0 })),
  trades: trades(),
  skipped: { max_trades_per_day: 3 },
  skipped_text: [
    {
      code: "max_trades_per_day",
      text: "The daily trade limit was already reached.",
      count: 3,
    },
  ],
  assumptions: [
    {
      code: "entry_next_open",
      text: "Entries fill at the open of the bar after the signal.",
    },
    {
      code: "stop_first",
      text: "When a bar touches both stop and target, the stop is assumed to have hit first.",
    },
  ],
  targets: targets(),
  baseline: { name: "buy and hold", net_return_pct: 1.2 },
  monte_carlo: { iterations: 1000, final_return_pct: { p5: -2.1, p50: 6.0, p95: 14.2 } },
  bootstrap: {
    expectancy_r: { low: -0.1, high: 0.7 },
    monthly_return: { low: -0.4, high: 1.9 },
  },
  ...over,
});

export const run = (over: Partial<RunOut> = {}): RunOut => ({
  id: 7,
  kind: "backtest",
  status: "done",
  progress: 100,
  message: null,
  name: "London breakout 2025",
  strategy_version_id: null,
  config: config(),
  request: {},
  data_fingerprint: "abcdef1234567890",
  config_version: 1,
  app_version: "0.8.0-rc1",
  summary: {
    net_return_pct: 6.24,
    total_trades: 30,
    expectancy_r: 0.31,
    max_drawdown_pct: 3.4,
    profit_factor: 2.27,
  },
  error: null,
  created_at: "2026-10-10T08:00:00Z",
  started_at: "2026-10-10T08:00:01Z",
  finished_at: "2026-10-10T08:00:09Z",
  ...over,
});

export const backtestDetail = (): RunDetail => ({ run: run(), result: backtestResult() });

const summary = (net: number) => ({
  window: { start: "2025-01-01T00:00:00Z", end: "2025-06-30T00:00:00Z" },
  metrics: metrics({ net_return_pct: net }),
  months: [{ month: "2025-01", return_pct: net }],
  equity_curve: equity(),
  trade_count: 12,
});

export const scorecard = (
  rank: number,
  name: string,
  over: Partial<Scorecard> = {},
): Scorecard => ({
  name,
  strategy: name.toLowerCase().replace(/ /g, "_"),
  rank,
  robustness_score: 80 - rank * 10,
  verdict: {
    code: "inconclusive",
    text: `Verdict text for ${name}: the evidence is mixed.`,
  },
  flags:
    rank === 2
      ? [{ code: "oos_negative", text: "Out-of-sample expectancy is negative." }]
      : [],
  full: {
    net_return_pct: 6.2,
    max_drawdown_pct: 3.4,
    profit_factor: 1.8,
    win_rate_pct: 55,
    expectancy_r: 0.2,
    total_trades: 120,
    monthly: { profitable_months: 8, losing_months: 4 },
  },
  out_of_sample: { expectancy_r: rank === 2 ? -0.1 : 0.15 },
  stressed: { net_return_pct: 2.1 },
  stability: { score: 0.7 },
  ...over,
});

export const researchResult = (): ResearchResult => ({
  type: "research",
  split: {
    development: { start: "2025-01-01T00:00:00Z", end: "2025-07-31T00:00:00Z" },
    validation: { start: "2025-08-01T00:00:00Z", end: "2025-10-15T00:00:00Z" },
    test: { start: "2025-10-16T00:00:00Z", end: "2025-12-31T00:00:00Z" },
  },
  optimisation: {
    space: { "params.risk_reward": [1.5, 2, 3] },
    rows: [
      { "params.risk_reward": 1.5, net_return_pct: 3.1, trades: 40 },
      { "params.risk_reward": 2, net_return_pct: 4.0, trades: 38 },
    ],
    best: { "params.risk_reward": 2, net_return_pct: 4.0 },
  },
  chosen_params: { "params.risk_reward": 2 },
  selection_note: {
    code: "selected_on_development",
    text: "Parameters were chosen on the development window only.",
  },
  development: summary(4.0),
  validation: summary(1.5),
  test: summary(-0.8),
  walk_forward: {
    folds: [
      { fold: 1, net_return_pct: 1.1 },
      { fold: 2, net_return_pct: -0.3 },
    ],
    oos_summary: { net_return_pct: 0.8 },
    efficiency: 0.45,
  },
  sensitivity: {
    "params.risk_reward": [
      { value: 1.5, net_return_pct: 3.1 },
      { value: 3, net_return_pct: 2.2 },
    ],
  },
  stability: {
    score: 0.7,
    note: { code: "moderate", text: "Neighbouring settings gave similar results." },
  },
  cost_stress: [
    { multiplier: 1, net_return_pct: 4.0 },
    { multiplier: 2, net_return_pct: 1.2 },
  ],
  monte_carlo: { iterations: 1000, max_drawdown_pct: { p50: 4.0, p95: 9.1 } },
  bootstrap: { expectancy_r: { low: -0.1, high: 0.5 } },
  regimes: [
    { regime: "trending", trades: 20, net_return_pct: 3.0 },
    { regime: "ranging", trades: 18, net_return_pct: -0.4 },
  ],
  baseline: { name: "random entries", net_return_pct: -1.0 },
  targets: { full: targets(), out_of_sample: targets() },
  scorecard: scorecard(1, "London breakout"),
});

export const compareResult = (): CompareResult => ({
  type: "compare",
  window: { start: "2025-01-01T00:00:00Z", end: "2025-12-31T00:00:00Z" },
  split: {},
  // Deliberately out of order: the table must order by rank itself.
  scorecards: [
    scorecard(2, "RSI pullback"),
    scorecard(3, "Bollinger reversion"),
    scorecard(1, "London breakout"),
  ],
  per_strategy: {},
});

export const importBatch = (): ImportBatch => ({
  id: 5,
  symbol: "EURUSD",
  timeframe: "5m",
  source: "csv",
  filename: "eurusd.csv",
  rows_total: 101,
  rows_accepted: 100,
  rows_inserted: 90,
  rows_existing: 10,
  error_count: 1,
  errors: [{ line: 4, message: "bad price" }],
  detected_format: "generic",
  start: "2025-01-01T00:00:00Z",
  end: "2025-01-02T00:00:00Z",
  quality: null,
  notes: [],
  created_at: "2026-10-10T08:00:00Z",
});

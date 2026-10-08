import type {
  BacktestOut,
  BookOut,
  CandleOut,
  ConfigOut,
  FieldBounds,
  MetricsOut,
  SignalOut,
  StatusOut,
  StrategyConfigOut,
  TradeOut,
} from "./types";

/** Test fixtures shared by the btc-range suites. Not imported by the app. */

export const metrics = (over: Partial<MetricsOut> = {}): MetricsOut => ({
  trades: 10,
  wins: 6,
  losses: 4,
  win_rate: "60.0",
  net_pnl: "125.50",
  gross_profit: "300.00",
  gross_loss: "174.50",
  profit_factor: "1.72",
  expectancy: "12.55",
  max_drawdown_pct: "3.40",
  return_pct: "1.26",
  ending_equity: "10125.50",
  ...over,
});

export const trade = (over: Partial<TradeOut> = {}): TradeOut => ({
  side: "long",
  signal_at: "2026-10-07T07:55:00Z",
  entry_at: "2026-10-07T08:00:00Z",
  entry_price: "66000.00",
  take_profit: "67000.00",
  stop_loss: "65500.00",
  quantity: "0.1",
  notional: "6600.00",
  exit_at: "2026-10-07T10:00:00Z",
  exit_price: "67000.00",
  exit_reason: "take_profit",
  fees: "6.60",
  pnl: "93.40",
  r_multiple: "1.87",
  ...over,
});

export const candles = (n = 12): CandleOut[] =>
  Array.from({ length: n }, (_, i) => {
    const base = 66000 + (i % 4) * 150;
    const start = new Date(Date.UTC(2026, 9, 8, 0, 0) + i * 900_000).toISOString();
    return {
      t: start,
      o: String(base),
      h: String(base + 120),
      l: String(base - 90),
      c: String(base + (i % 2 === 0 ? 60 : -40)),
    };
  });

export const signal = (over: Partial<SignalOut> = {}): SignalOut => ({
  at: "2026-10-08T03:00:00Z",
  price: "66120.00",
  call: "long",
  confidence: 72,
  range: {
    support: "65800.00",
    resistance: "67200.00",
    mid: "66500.00",
    width_pct: "2.13",
    position: "0.23",
    touches_support: 3,
    touches_resistance: 3,
    trend_efficiency: "0.18",
    confidence: 72,
    regime: "range",
  },
  entry: "66120.00",
  take_profit: "66950.00",
  stop_loss: "65700.00",
  reward_risk: "1.98",
  reasons: [
    { code: "near_support", text: "Price is in the lower fifth of the range." },
    { code: "support_touches", text: "Support has been touched 3 times." },
  ],
  ...over,
});

export const waitSignal = (): SignalOut =>
  signal({
    call: "wait",
    confidence: 41,
    entry: null,
    take_profit: null,
    stop_loss: null,
    reward_risk: null,
    reasons: [{ code: "mid_range", text: "Price is in the middle of the range." }],
  });

export const book = (over: Partial<BookOut> = {}): BookOut => ({
  started_at: "2026-10-01T00:00:00Z",
  config_version: 3,
  config: defaults,
  metrics: metrics(),
  long: metrics({ trades: 6, wins: 4, losses: 2, win_rate: "66.7", net_pnl: "90.00" }),
  short: metrics({
    trades: 4,
    wins: 2,
    losses: 2,
    win_rate: "50.0",
    net_pnl: "-12.25",
    profit_factor: null,
  }),
  open_position: null,
  trades: [
    trade(),
    trade({
      side: "short",
      exit_reason: "stop_loss",
      pnl: "-40.10",
      r_multiple: "-1.00",
      entry_at: "2026-10-06T08:00:00Z",
      exit_at: "2026-10-06T09:00:00Z",
    }),
  ],
  equity_curve: [
    { at: "2026-10-01T00:00:00Z", equity: "10000.00" },
    { at: "2026-10-04T00:00:00Z", equity: "10080.00" },
    { at: "2026-10-08T00:00:00Z", equity: "10125.50" },
  ],
  ...over,
});

export const status = (over: Partial<StatusOut> = {}): StatusOut => ({
  running: true,
  reason: null,
  symbol: "BTC/USDT",
  timeframe: "15m",
  paper_only: true,
  price: { value: "66123.45", at: "2026-10-08T03:05:00Z", candle_closed: true },
  data: {
    candles: 192,
    first_at: "2026-10-06T00:00:00Z",
    last_closed_at: "2026-10-08T03:00:00Z",
    stale: false,
  },
  signal: signal(),
  book: book(),
  candles: candles(),
  ...over,
});

const b = (
  kind: FieldBounds["kind"],
  group: FieldBounds["group"],
  label: string,
  min: string,
  max: string,
  step: string,
): FieldBounds => ({ kind, group, label, min, max, step, help: `${label} help.` });

export const defaults: StrategyConfigOut = {
  lookback: 96,
  touch_tolerance: "0.0015",
  min_touches: 2,
  min_width_pct: "1.0",
  max_width_pct: "6.0",
  max_trend_efficiency: "0.35",
  min_confidence: 60,
  entry_zone: "0.2",
  tp_target: "0.5",
  sl_buffer: "0.003",
  min_reward_risk: "1.5",
  max_hold_candles: 48,
  cooldown_candles: 4,
  allow_long: true,
  allow_short: true,
  starting_balance: "10000",
  risk_per_trade_pct: "1.0",
  max_leverage: "2",
  fee_bps: "10",
  slippage_bps: "2",
};

export const config = (over: Partial<ConfigOut> = {}): ConfigOut => ({
  config_version: 3,
  defaults,
  bounds: {
    lookback: b("int", "range", "Lookback candles", "24", "500", "1"),
    touch_tolerance: b("decimal", "range", "Touch tolerance", "0.0001", "0.01", "0.0001"),
    min_touches: b("int", "range", "Minimum touches", "2", "10", "1"),
    min_width_pct: b("decimal", "range", "Minimum width %", "0.2", "10", "0.1"),
    max_width_pct: b("decimal", "range", "Maximum width %", "1", "20", "0.1"),
    max_trend_efficiency: b(
      "decimal",
      "range",
      "Max trend efficiency",
      "0.05",
      "1",
      "0.01",
    ),
    min_confidence: b("int", "entries", "Minimum confidence", "0", "100", "1"),
    entry_zone: b("decimal", "entries", "Entry zone", "0.05", "0.45", "0.01"),
    tp_target: b("decimal", "entries", "TP target", "0.1", "1", "0.05"),
    sl_buffer: b("decimal", "entries", "SL buffer", "0.0005", "0.02", "0.0005"),
    min_reward_risk: b("decimal", "entries", "Minimum reward:risk", "0.5", "5", "0.1"),
    max_hold_candles: b("int", "entries", "Max candles in a trade", "1", "500", "1"),
    cooldown_candles: b("int", "entries", "Cooldown candles", "0", "100", "1"),
    allow_long: b("bool", "entries", "Allow LONG calls", "0", "1", "1"),
    allow_short: b("bool", "entries", "Allow SHORT calls", "0", "1", "1"),
    starting_balance: b("decimal", "account", "Starting balance", "100", "1000000", "100"),
    risk_per_trade_pct: b("decimal", "account", "Risk per trade %", "0.1", "5", "0.1"),
    max_leverage: b("decimal", "account", "Max leverage", "1", "10", "0.5"),
    fee_bps: b("decimal", "account", "Fee (bps)", "0", "100", "0.5"),
    slippage_bps: b("decimal", "account", "Slippage (bps)", "0", "100", "0.5"),
  },
  data_first_at: "2026-08-01T00:00:00Z",
  data_last_at: "2026-10-08T03:00:00Z",
  ...over,
});

export const backtest = (over: Partial<BacktestOut> = {}): BacktestOut => ({
  available: true,
  reason: null,
  config: { ...defaults, lookback: 120 },
  start: "2026-09-08T00:00:00Z",
  end: "2026-10-08T03:00:00Z",
  candles: 2900,
  signal_counts: { long: 14, short: 9, wait: 2877 },
  wait_reasons: [
    { code: "mid_range", text: "Price was in the middle of the range.", count: 1500 },
    { code: "no_range", text: "No tradable range was found.", count: 1377 },
  ],
  metrics: metrics(),
  long: metrics({ trades: 14, net_pnl: "200.00" }),
  short: metrics({ trades: 9, net_pnl: "-74.50", profit_factor: null }),
  trades: [trade()],
  equity_curve: [
    { at: "2026-09-08T00:00:00Z", equity: "10000" },
    { at: "2026-10-08T00:00:00Z", equity: "10125.50" },
  ],
  ...over,
});

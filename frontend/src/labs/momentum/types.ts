/** Shapes of `/labs/momentum/*`. Every figure is computed on the backend. */

export interface MomentumStatus {
  running: boolean;
  min_age_days: number;
  min_liquidity_usd: number;
  start_usd: number;
  ticket_usd: number;
  arms: number;
  pools_active: number;
  pools_sampled_5m: number;
  last_sample_at: string | null;
  seconds_since_sample: number | null;
  last_close: Record<string, string>;
  signals_24h: number;
  open_positions: number;
  closed_trades: number;
  started_at: string | null;
}

export interface SplitRow {
  split: number;
  ticket: number;
  end: number;
  low: number;
  funded: number;
  skipped: number;
}

export interface ArmRow {
  name: string;
  family: string;
  tf: string;
  note: string;
  entry: string;
  exit: string;
  is_control: boolean;
  vs: string | null;
  trades: number;
  open: number;
  wins: number;
  mean_pct: number | null;
  median_pct: number | null;
  se_pct: number | null;
  pf: number | null;
  best_pct: number | null;
  worst_pct: number | null;
  gross_pct: number | null;
  book_usd: number;
  unrealised_usd: number;
  wallet: SplitRow;
  splits: SplitRow[];
  z_vs: number | null;
  verdict: string;
}

export interface MomentumBoard {
  running: boolean;
  generated_at: string | null;
  started_at: string | null;
  arms: ArmRow[];
}

export interface TradeRow {
  arm: string;
  status: string;
  symbol: string | null;
  mint: string;
  pair_address: string;
  dex_id: string | null;
  signal_tf: string;
  signal_start: string;
  signal_open: number;
  signal_high: number;
  signal_low: number;
  signal_close: number;
  features: Record<string, number | null | Record<string, number | null>> | null;
  decided_at: string;
  opened_at: string | null;
  open_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  peak_price: number | null;
  closed_at: string | null;
  close_price: number | null;
  exit_reason: string | null;
  net_return_pct: number | null;
  pnl_usd: number | null;
  last_price: number | null;
}

export interface MomentumTrades {
  arm: string;
  trades: TradeRow[];
}

export interface SignalRow {
  symbol: string | null;
  mint: string;
  pair_address: string;
  tf: string;
  start: string;
  at: string;
  arms: string[];
  features: Record<string, number | null>;
}

export interface MomentumSignals {
  signals: SignalRow[];
}

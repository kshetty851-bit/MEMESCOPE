/**
 * The Rafiq Lab's wire types.
 *
 * Every money and price field is a STRING, matching the backend. A JSON number
 * for a token priced at 4.8e-10 loses precision on the way through, and a
 * ledger that renders a different number from the one it stored is not a
 * ledger. Formatting happens at the edge, in `format.ts`; arithmetic does not
 * happen here at all.
 */

export interface RafiqStrategy {
  code: string;
  name: string;
  lane: string;
  /** The one-line question this book exists to answer. */
  question: string;
  /** Null for a book with no take profit at all — D2, and C2's second leg. */
  take_profit_mult: string | null;
  stop_mult: string;
  trailing_frac: string | null;
  max_hold_hours: string;
  entry_threshold: string;
  liquidity_derived_risk: boolean;
  daily_breaker: boolean;
  consensus_gate: boolean;
  /**
   * False for a retired book. It still settles its open positions under the
   * geometry frozen on each row, but opens nothing new — so its equity is its
   * last value, not a current one.
   */
  enters: boolean;
  /** F2 only: the equity level at which it stops opening positions. */
  equity_floor: string | null;
  /** F2 only: its daily entry cap. */
  max_trades_per_day: number | null;
  /** The v2 entry gate's thresholds, as published. */
  gate: Record<string, string>;
  starting_equity: string;
  execution_cost_usd: string;
  cash: string;
  equity: string;
  realised_pnl: string;
  unrealised_pnl: string;
  open_positions: number;
  closed_trades: number;
  wins: number;
  losses: number;
  /** Realised P&L before fee and price impact — the gross-vs-net pair is what
   *  separates "everything loses" from "this book is dying to friction". */
  gross_pnl_ex_fees: string;
  mean_pnl_per_trade_net: string | null;
  mean_pnl_per_trade_gross: string | null;
  entries_rejected_by_gate: number;
  rejection_reason_counts: Record<string, number>;
  equity_curve: string[];
  activated_at: string;
}

export interface RafiqStatus {
  running: boolean;
  starting_equity: string;
  strategies: RafiqStrategy[];
}

export interface RafiqPosition {
  /** 1 for every book but C2, which opens two legs per token. */
  leg: number;
  strategy_code: string;
  mint_address: string;
  symbol: string | null;
  opened_at: string;
  age_seconds: number;
  entry_price: string;
  quantity: string;
  cost_basis: string;
  stop_price: string;
  stop_pct: string;
  /** Null when this leg has no take profit. */
  target_price: string | null;
  trailing_frac: string | null;
  max_hold_hours: string;
  peak_price: string;
  last_mark_price: string | null;
  current_value: string | null;
  unrealised_pnl: string | null;
  status: string;
}

export interface RafiqTrade {
  /** 1 for every book but C2, which opens two legs per token. */
  leg: number;
  strategy_code: string;
  mint_address: string;
  symbol: string | null;
  opened_at: string;
  closed_at: string;
  hold_seconds: number;
  entry_price: string;
  exit_price: string;
  exit_observed_price: string;
  cost_basis: string;
  proceeds_usd: string;
  realised_pnl: string;
  return_pct: string;
  exit_reason: string;
  exit_evidence: string | null;
  if_held_value: string | null;
  if_held_pct: string | null;
}

export interface RafiqBreaker {
  strategy_code: string;
  gates_entries: boolean;
  day: string;
  day_open_equity: string;
  realised_today: string;
  halted: boolean;
  halted_reason: string | null;
  halted_at: string | null;
}

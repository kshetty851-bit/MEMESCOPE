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
  take_profit_mult: string;
  stop_mult: string;
  trailing_frac: string | null;
  max_hold_hours: string;
  entry_threshold: string;
  liquidity_derived_risk: boolean;
  daily_breaker: boolean;
  consensus_gate: boolean;
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
  equity_curve: string[];
  activated_at: string;
}

export interface RafiqStatus {
  running: boolean;
  starting_equity: string;
  strategies: RafiqStrategy[];
}

export interface RafiqPosition {
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
  target_price: string;
  trailing_frac: string | null;
  max_hold_hours: string;
  peak_price: string;
  last_mark_price: string | null;
  current_value: string | null;
  unrealised_pnl: string | null;
  status: string;
}

export interface RafiqTrade {
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

"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

/**
 * RAFIQV2 CLIENT — fetches, never decides. Every figure arrives computed by
 * the same functions the lab's tick uses; there is no write route.
 */

export interface Rafiqv2Rules {
  entry_gate: {
    min_liquidity_usd: number;
    min_market_cap_usd: number;
    max_impact_pct: number;
  };
  entry_score_min: number;
  exits: {
    stop: number;
    max_hold_minutes: number;
    scale_out: { at_multiple: number; sell_fraction: number } | null;
    runner_trail_frac: number;
  };
  fast_rug_gates: {
    ladder: { after_seconds: number; min_multiple: number; label: string }[];
  };
  profit_lock: {
    ladder: { once_peak_reaches_pct: number; never_sell_below_pct: number }[];
  };
  death_rate_breaker: {
    window: number;
    halt_at_death_rate_pct: number;
    min_sample: number;
    halt_for_hours: number;
  };
  equity_ratchet: { give_back_pct: number; initial_floor_usd: number };
  daily_breaker: { max_daily_drawdown_pct: number; max_daily_realised_loss_pct: number };
  sizing: {
    position_pct_of_book: number;
    min_position_usd: number;
    max_position_usd: number;
  };
}

export interface Rafiqv2Adjustment {
  at: string;
  parameter: string;
  old_value: string;
  new_value: string;
  sample_size: number | null;
  z_score: string | null;
  reason: string;
}

export interface Rafiqv2Book {
  code: string;
  name: string;
  identity: string;
  rules: Rafiqv2Rules;
  activated_at: string | null;
  starting_equity: string;
  cash: string | null;
  equity: string | null;
  realised_pnl: string | null;
  unrealised_pnl: string | null;
  open_positions: number;
  closed_trades: number;
  wins: number;
  losses: number;
  mean_net_per_trade: string | null;
  halted: string[];
  ratchet_floor: string | null;
  ratchet_high_water: string | null;
  window_deaths: number;
  window_trades: number;
  learning: {
    rug_strictness: number;
    lock_giveback: number;
    size_multiplier: number;
    regime_note: string;
    closes_learned: number;
    closes_awaiting_their_hour: number;
  } | null;
  adjustments: Rafiqv2Adjustment[];
}

export interface Rafiqv2Status {
  running: boolean;
  books: Rafiqv2Book[];
}

export interface Rafiqv2Position {
  book: string;
  mint_address: string;
  symbol: string | null;
  opened_at: string;
  age_seconds: number;
  cost_basis: string;
  multiple: string | null;
  peak_multiple: string;
  lock_floor: string | null;
  scaled_out: boolean;
  fraction_open: string;
  current_value: string;
  unrealised_pnl: string;
  rug_strictness: string;
  lock_giveback: string;
  size_multiplier: string;
}

export interface Rafiqv2Trade {
  book: string;
  mint_address: string;
  symbol: string | null;
  opened_at: string;
  closed_at: string;
  hold_seconds: number;
  cost_basis: string;
  proceeds_usd: string;
  pnl_usd: string;
  return_pct: string;
  exit_reason: string;
  exit_evidence: string | null;
  scaled_out: boolean;
  died: boolean | null;
  peak_multiple: string;
  forward_peak_multiple: string | null;
  entry_top10_holder_pct: string | null;
  entry_lp_locked: boolean | null;
}

/** The lab ticks every 30s; polling faster would fetch numbers that cannot have moved. */
const POLL_MS = 30_000;

export function useRafiqv2Status() {
  return useQuery({
    queryKey: ["rafiqv2", "status"],
    refetchInterval: POLL_MS,
    queryFn: () => api.get<Rafiqv2Status>("/labs/rafiqv2/status"),
  });
}

export function useRafiqv2Positions() {
  return useQuery({
    queryKey: ["rafiqv2", "positions"],
    refetchInterval: POLL_MS,
    queryFn: () => api.get<Rafiqv2Position[]>("/labs/rafiqv2/positions"),
  });
}

export function useRafiqv2Trades() {
  return useQuery({
    queryKey: ["rafiqv2", "trades"],
    refetchInterval: POLL_MS,
    queryFn: () => api.get<Rafiqv2Trade[]>("/labs/rafiqv2/trades?limit=200"),
  });
}

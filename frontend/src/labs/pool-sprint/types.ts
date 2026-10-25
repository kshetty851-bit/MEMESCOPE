export interface SprintSummary {
  creator_skipped?: number;
  capital_usd: string;
  ticket_usd: string;
  cost_usd: string;
  balance_usd: string;
  pnl_usd: string;
  trades: number;
  skipped: number;
  rugs: number;
  lowest_usd: string;
}

export interface SprintDay {
  creator_skipped?: number;
  date: string;
  n: number;
  running: boolean;
  from: string;
  to: string;
  opened: number;
  trades: number;
  priced: number;
  unpriced: number;
  rugs: number;
  skipped: number;
  pnl_usd: string;
  balance_usd: string;
  pct: string;
}

export interface SprintTrade {
  creator?: string | null;
  blocked_since?: string;
  graduated_at?: string | null;
  entry_buys?: number | null;
  entry_sells?: number | null;
  quote_mint?: string | null;
  base_mint?: string | null;
  pair_evidence?: string | null;
  mint: string;
  symbol: string | null;
  name?: string | null;
  pair?: string;
  opened_at: string;
  closed_at?: string | null;
  pool_usd: string;
  entry_price?: string;
  exit_price?: string | null;
  status: "priced" | "unpriced" | "open" | "cash_skipped" | "creator_blocked";
  pct?: string | null;
  pnl_usd?: string | null;
  rugged?: boolean;
  source?: string | null;
}

export interface SprintTrades {
  total: number;
  offset: number;
  limit: number;
  as_of: string;
  trades: SprintTrade[];
}

export interface SprintBook extends SprintSummary {
  blocked_creators?: number;
  creator_rule?: string;
  excluded_entry_rule?: number;
  entry_rule?: string;
  pool_candidates?: number;
  excluded_non_sol?: number;
  unverified_pools?: number;
  name: string;
  book: string;
  rule: string;
  started_at: string;
  as_of: string;
  snapshot_at: string;
  live_read_as_of: string | null;
  refreshing: boolean;
  refresh_error: boolean;
  hold_minutes: number;
  signals: number;
  closed: number;
  open: number;
  unpriced: number;
  wins: number;
  free_cash_usd: string;
  open_stake_usd: string;
  priced_pnl_usd: string;
  pricing_reserve_usd: string;
  lowest_cash_usd: string;
  max_concurrent: number;
  dex_exits: number;
  candle_exits: number;
  days: SprintDay[];
  start_dates: (Pick<
    SprintSummary,
    "balance_usd" | "pnl_usd" | "lowest_usd" | "trades" | "rugs" | "skipped"
  > & {
    start: string;
    days: number;
  })[];
  sizes: {
    ticket_usd: string;
    cells: Pick<
      SprintSummary,
      "balance_usd" | "pnl_usd" | "lowest_usd" | "trades" | "rugs" | "skipped"
    >[];
  }[];
  costs: SprintSummary[];
  bands: { low: number; high: number; trades: number; rugs: number; pnl_usd: string }[];
}

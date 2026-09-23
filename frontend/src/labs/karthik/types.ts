export interface KarthikTrade {
  symbol: string | null;
  opened_at: string;
  closed_at: string | null;
  pct: string;
  pnl_usd: string;
  pool_usd: string | null;
}

export interface KarthikBook {
  book: string;
  rule: string;
  hold_minutes: number;
  started_at: string;
  /** Fixed in config before the first trade. A judge date that moves is not a
      judge — it is the result choosing when to be measured. */
  judge_at: string;
  capital_usd: string;
  ticket_usd: string;
  balance_usd: string;
  pnl_usd: string;
  lowest_usd: string;
  trades: number;
  skipped: number;
  wins: number;
  rugs: number;
  /** The balance without its single luckiest trade. On the arm this copies,
      that one number is the difference between +$1,060 and about $100. */
  without_best_usd: string;
  trades_list: KarthikTrade[];
}

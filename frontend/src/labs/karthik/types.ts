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
  days: KarthikDay[];
  holds: KarthikHold[];
  trades_list: KarthikTrade[];
}

/** One 24-hour period since the book opened, newest first. */
export interface KarthikDay {
  n: number;
  from: string;
  to: string;
  /** True for the period still in progress, which is not yet a full day. */
  running: boolean;
  trades: number;
  pnl_usd: string;
  /** Of the balance this period OPENED with -- a day's return, not a share
   *  of the starting $500 like the figures above it. */
  pct: string;
  balance_usd: string;
}

/** The same coins, sold on a later clock. */
export interface KarthikHold {
  minutes: number;
  coins: number;
  pnl_usd: string;
  per_trade_pct: string;
  /** Coins worth under a tenth of the entry by then. */
  wiped: number;
  /** True for the row the book actually trades, which is net of its costs. */
  book: boolean;
}

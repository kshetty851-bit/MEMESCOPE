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
  /** When the book changed size. Chosen after its first day was seen, so what
   *  came before is in sample for the size; only what follows is a fair test. */
  resized_at: string;
  previous_capital_usd: string;
  previous_ticket_usd: string;
  capital_usd: string;
  ticket_usd: string;
  balance_usd: string;
  pnl_usd: string;
  lowest_usd: string;
  trades: number;
  skipped: number;
  wins: number;
  rugs: number;
  days: KarthikDay[];
  holds: KarthikHold[];
  whatif: KarthikWhatIf;
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

/** One way of trading the same book: its balance and record on those terms. */
export interface KarthikWhatIfLine {
  balance_usd: string;
  pnl_usd: string;
  pnl_pct: string;
  trades: number;
  skipped: number;
  rugs: number;
  lowest_usd: string;
}

/** The same trades at other sizes, and on $150k+ pools only. A check shown
 *  beside the book; the book itself stays on its own rule. */
export interface KarthikWhatIf {
  floor_usd: number;
  deep: KarthikWhatIfLine;
  sizes: { ticket_usd: number; current: boolean; all: KarthikWhatIfLine; deep: KarthikWhatIfLine }[];
}

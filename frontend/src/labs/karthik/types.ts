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
  /** Signals let go because a trade was already open: the one-at-a-time
   *  rule, not a lack of cash. */
  busy_skipped: number;
  /** When the book became one trade at a time. Replayed from day 1, so what
   *  came before is a look back chosen after seeing it. */
  one_at_a_time_since: string;
  /** The pools the book counts, [low, high) USD, and when that was chosen.
   *  Replayed from day 1, so what came before is a look back. */
  pools_usd?: [number, number | null];
  pools_since?: string;
  /** The old rule on the same start: every signal the cash allowed. */
  every_trade: KarthikWhatIfLine;
  wins: number;
  rugs: number;
  days: KarthikDay[];
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

/** One way of trading the same book: its balance and record on those terms. */
export interface KarthikWhatIfLine {
  /** Trades taken that were rebuilt from price snapshots, not taken live. */
  replayed?: number;
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
  floors: (KarthikWhatIfLine & { floor_usd: number })[];
  /** Pool-size splits, each its own one-at-a-time walk on the book's money.
   *  `book`: cut from this book's trades ($75k+). Otherwise from the arms that
   *  run the same rule on the pools the book skips; `replayed` of those trades
   *  were rebuilt from price snapshots rather than taken live. */
  bands?: (KarthikWhatIfLine & { lo_usd: number; hi_usd: number | null; book: boolean })[];
  sizes: { ticket_usd: number; capital_usd: number; current: boolean; all: KarthikWhatIfLine; deep: KarthikWhatIfLine }[];
}

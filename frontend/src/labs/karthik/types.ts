export interface KarthikTrade {
  symbol: string | null;
  /** The token's address: the page links it to DexScreener to verify. */
  mint?: string;
  opened_at: string;
  closed_at: string | null;
  pct: string;
  pnl_usd: string;
  pool_usd: string | null;
}

export interface KarthikBook {
  /** Every pump.fun graduation seen since the book opened, bought or not. */
  graduations_seen?: number;
  /** Of those whose first hour is over: how many fell 80%+ within it. */
  graduations_rugged?: { rugged: number; measured: number; window_minutes: number };
  /** Who traded the coins the book bought, graduation to its sell (on-chain). */
  flows?: KarthikFlows;
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
  /** Never buys a coin more than this long after it graduated (seconds). */
  max_entry_age_s?: number;
  max_entry_age_since?: string;
  /** A pool counts as quiet under this many trades. */
  quiet_max_txs?: number;
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
  /** The grid's pool floors, left to right. `book` marks this book's own
   *  floor; `replayed_below` marks floors that include the $25-75k pools the
   *  book skips (rebuilt from price snapshots before those arms went live). */
  floors: { floor_usd: number; book: boolean; replayed_below: boolean }[];
  /** One row per trade size, on the balance it is paired with; one cell per
   *  floor, each its own one-at-a-time walk from the book's start. */
  sizes: { ticket_usd: number; capital_usd: number; current: boolean; cells: KarthikWhatIfLine[] }[];
}

export interface KarthikFlows {
  trades: number;
  measured: number;
  insider_buy_usd: string;
  insider_sell_usd: string;
  other_buy_usd: string;
  other_sell_usd: string;
  insider_sold_trades: number;
  /** Absent from an older API. */
  insider_bought_trades?: number;
  other_buyers: number;
}


/** One Dubai calendar day of pump.fun, from `/labs/graduation/karthik/pumpfun-days`. */
export interface PumpfunDay {
  day: string;
  running: boolean;
  launches: number;
  graduations: number;
  /** SOL paid into the curves that graduated (85 each), in dollars. */
  into_curves_usd: string | null;
  /** Money in the new pools two minutes after graduating. */
  pools_usd: string;
  pools_75k: number;
}

export interface PumpfunDays {
  graduation_sol: number;
  days: PumpfunDay[];
}

/** One real wallet's closed trades: today (Dubai) and since it began. */
export interface WalletProfit {
  label: string;
  today_trades: number;
  today_won: number;
  today_pnl_usd: string;
  all_trades: number;
  all_pnl_usd: string;
}

export interface WalletsProfit {
  wallets: WalletProfit[];
}

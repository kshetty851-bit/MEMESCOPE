/** The Graduation Hold Lab board. Shapes mirror the server; accounting is server-side. */

export interface FiveMinPosition {
  id: string;
  mint: string;
  status: string;
  opened_at: string;
  size_usd: number | null;
  open_value: number | null;
  exec_multiple: number | null;
  exit_reason: string | null;
  pnl: number | null;
}

/** One arm. Both arms are identical except `hold_minutes`, which is the point. */
export interface FiveMinWallet {
  strategy_id: string;
  name: string;
  status: string;
  hypothesis: string;
  entry_text: string[];
  exit_text: string[];
  checkpoint_label: string;
  size_usd: number | null;
  max_concurrent: number | null;
  cash: number | null;
  open_value: number | null;
  equity: number | null;
  /** Counts, taken over every row rather than the display window. */
  open_positions: number;
  closed_positions: number;
  realised_pnl: number | null;
  trades: FiveMinPosition[];
  /** Contributed by the board's `axis` — the horizon this arm sells at. */
  hold_minutes: number | null;
  /** Contributed by the board's `axis` — e.g. "$2 x 50". The axis under test. */
  shape?: string | null;
  rank?: number;
}

export interface FiveMinBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  spec_hash: string;
  starting_equity: number | null;
  failure_floor?: number | null;
  /** Null when the registry runs no ratchet, which this one does not. */
  target_multiple: number | null;
  wallets?: FiveMinWallet[];
  /** The horizons under test, shortest first. */
  hold_minutes?: number[];
  /** Flat, and never follows the balance. */
  stake_usd?: string;
  sizing_scales?: boolean;
  /** False by design: the wallet ratchet was removed. */
  cycle_enabled?: boolean;
  /** "graduations" — the cohort the hypothesis came from. */
  candidate_source?: string;
  /** Minutes after graduation at which a coin is judged. */
  checkpoint_minutes?: number;
  /** Execution fidelity, not a signal. */
  liquidity_floor?: string;
  /** The book shapes under test, smallest stake first. */
  book_shapes?: string[];
}

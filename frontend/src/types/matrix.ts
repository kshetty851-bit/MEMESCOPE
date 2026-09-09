/** The Matrix Lab board. A grid, not a list — the axes come from the server. */

import type { MoversWallet } from "@/types/movers";

/** One cell of the grid: a wallet plus the three coordinates that place it. */
export interface MatrixWallet extends MoversWallet {
  /** "FRESH" | "AGED" — which population this arm draws from. */
  section: string | null;
  /** Minutes held, or null for the arms whose only exit is the wallet ratchet. */
  clock_minutes: number | null;
  /** "$10 x 10" — stake and slot count, always multiplying to the book. */
  shape: string | null;
  /** radar | deepamm — the candidate stream, which IS the population. */
  source: string | null;
}

export interface MatrixBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  valid_from?: string;
  spec_hash?: string;
  starting_equity?: number;
  wallets: MatrixWallet[];
  sections?: string[];
  min_liquidity_usd?: string;
  min_age_hours?: string;
  target_multiple?: string;
}

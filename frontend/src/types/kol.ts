/** The KOL Lab board and its frozen wallet ranking. */

import type { MoversWallet } from "@/types/movers";

/** Same shape as the Movers arms — both run on the shared lab board. */
export type KolWallet = MoversWallet;

export interface KolBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  valid_from?: string;
  starting_equity?: number;
  wallets: KolWallet[];
  hold_minutes?: number;
  min_liquidity_usd?: number;
}

/** One wallet the tournament follows, with the evidence that selected it. */
export interface KolRankedWallet {
  rank: number;
  wallet: string;
  early_buys: number;
  hits: number;
  hit_rate: number;
}

export interface KolWallets {
  disclosure: string;
  /** False until enough history exists to rank on. */
  frozen: boolean;
  computed_at: string | null;
  min_early_buys: number;
  hit_horizon_hours: number;
  hit_multiple: number;
  /** What a hit rate has to beat to mean anything. Null when nothing scored. */
  base_rate: number | null;
  base_rate_sample: number;
  wallets: KolRankedWallet[];
}

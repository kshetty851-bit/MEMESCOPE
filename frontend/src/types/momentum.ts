/** Momentum V2: twenty pump.fun wallets, each ratcheting at +10%. */

export interface MomentumWallet {
  rank: number;
  strategy_id: string;
  name: string;
  status: string;
  /** A random control — no momentum condition. The eighteen cannot be read
   *  without these two beside them. */
  is_control: boolean;
  entry_text: string[];
  cash: number;
  open_value: number;
  equity: number;
  open_positions: number;
  cycles_banked: number;
  cycle_no: number | null;
  base_usd: number | null;
  target_usd: number | null;
  last_realised: number | null;
}

export interface MomentumBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  spec_hash: string;
  starting_equity: number;
  target_multiple: number;
  wallets: MomentumWallet[];
}

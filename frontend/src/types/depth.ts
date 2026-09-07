/** The depth curve: twenty wallets differing only in their liquidity floor. */

export interface DepthCell {
  rank: number;
  strategy_id: string;
  name: string;
  status: string;
  /** The x-axis. Without it there is no curve. */
  floor_usd: number;
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

export interface DepthBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  spec_hash: string;
  starting_equity: number;
  target_multiple: number;
  wallets: DepthCell[];
}

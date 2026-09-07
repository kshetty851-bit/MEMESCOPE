/** The depth curve: twenty wallets differing only in their liquidity floor. */

export interface DepthTrade {
  id: string;
  mint: string;
  status: string;
  opened_at: string;
  closed_at: string | null;
  size_usd: number;
  value: number | null;
  exec_multiple: number | null;
  exit_reason: string | null;
  pnl: number | null;
}

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
  hypothesis: string;
  exit_text: string[];
  checkpoint_label: string;
  size_usd: number;
  max_concurrent: number;
  closed_positions: number;
  /** Counted over EVERY row, not over the windowed `trades` list below. */
  realised_pnl: number;
  trades: DepthTrade[];
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

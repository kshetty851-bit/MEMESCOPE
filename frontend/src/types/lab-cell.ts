/**
 * One wallet on a compound-ratchet board.
 *
 * Depth and Social are the same row with a different x-axis, so the shape they
 * share lives here and each board extends it with the column only it has.
 */
export interface LabTrade {
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

export interface LabCell {
  rank: number;
  strategy_id: string;
  name: string;
  status: string;
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
  trades: LabTrade[];
  cycles_banked: number;
  cycle_no: number | null;
  base_usd: number | null;
  target_usd: number | null;
  last_realised: number | null;
}

export interface LabBoard<C extends LabCell> {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  spec_hash: string;
  starting_equity: number;
  target_multiple: number;
  wallets: C[];
}

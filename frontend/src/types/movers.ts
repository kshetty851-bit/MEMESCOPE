/** The Movers Lab board. Shapes mirror the server; accounting is server-side. */

export interface MoversPosition {
  id: string;
  mint: string;
  status: string;
  opened_at: string;
  closed_at: string | null;
  size_usd: number | null;
  value: number | null;
  exec_multiple: number | null;
  exit_reason: string | null;
  pnl: number | null;
}

/** One arm. The two are identical except the turnover condition. */
export interface MoversWallet {
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
  open_positions: number;
  closed_positions: number;
  realised_pnl: number | null;
  trades: MoversPosition[];
  /** True for MOV-02. The page must never present the control as a result. */
  is_control?: boolean;
}

export interface MoversBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  /** When the tournament was frozen; the page shows elapsed time from it. */
  valid_from?: string;
  spec_hash?: string;
  status?: string;
  starting_equity?: number;
  wallets: MoversWallet[];
  /** Served rather than hardcoded, so the page cannot drift from the engine. */
  turnover_floor?: number;
  min_liquidity_usd?: number;
  hold_minutes?: number;
}

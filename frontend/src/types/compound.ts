/** The Compound Lab: one wallet, a target on the WALLET, compounding cycles. */

export interface CompoundCycle {
  cycle_no: number;
  base_usd: number;
  target_usd: number;
  started_at: string;
  reached_at: string | null;
  /** Equity on marks when the target tripped — what was aimed at. */
  equity_at_target: number | null;
  /** Equity after the book was actually sold — what was banked, and the base
   *  of the next cycle. Lower than the target by the impact of selling. */
  realised_equity: number | null;
  positions_closed: number;
  outcome: string | null;
}

export interface CompoundPosition {
  id: string;
  mint: string;
  status: string;
  opened_at: string;
  size_usd: number;
  open_value: number | null;
  exec_multiple: number | null;
  exit_reason: string | null;
  pnl: number | null;
}

/** The frozen rule this wallet trades, as the engine judges with it. */
export interface CompoundRules {
  id: string;
  name: string;
  hypothesis: string;
  checkpoint_label: string;
  entry_text: string[];
  exit_text: string[];
  size_usd: string;
  max_concurrent: number;
  max_exposure_usd: string;
  evidence: string;
  overfit_risk: string;
}

export interface CompoundBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  spec_hash: string;
  strategy_id?: string;
  name?: string;
  rules?: CompoundRules;
  starting_equity: number;
  target_multiple: number;
  failure_floor?: number;
  cash?: number;
  open_value?: number;
  equity?: number;
  status?: string;
  cycles_banked?: number;
  current_cycle: {
    cycle_no: number;
    base_usd: number;
    target_usd: number;
    started_at: string;
  } | null;
  cycles: CompoundCycle[];
  positions: CompoundPosition[];
}

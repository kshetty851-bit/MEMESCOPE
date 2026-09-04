/** The PumpFun copy lab: one leader, mirrored forward only. */

export interface PumpfunSignal {
  signature: string;
  mint: string;
  side: "buy" | "sell";
  leader_sol: number | null;
  leader_at: string;
  seen_at: string;
  /** How far behind him we were. The experiment measures this, not just P&L. */
  lag_seconds: number;
  acted: boolean;
  outcome: string;
}

export interface PumpfunPosition {
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

export interface PumpfunCoverage {
  signals_seen?: number;
  /** Signals from after the lab started — the ones we could have acted on. */
  actionable?: number;
  copied?: number;
  copied_pct?: number | null;
  by_outcome?: Record<string, number>;
  mean_lag_seconds?: number | null;
}

export interface PumpfunBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  spec_hash: string;
  leader_address: string;
  leader_label: string;
  starting_equity: number;
  max_signal_age_seconds: number;
  watching_from?: string;
  strategy_id?: string;
  name?: string;
  status?: string;
  cash?: number;
  open_value?: number;
  equity?: number;
  coverage: PumpfunCoverage;
  signals: PumpfunSignal[];
  positions: PumpfunPosition[];
  rules?: {
    id: string;
    name: string;
    hypothesis: string;
    exit_text: string[];
    size_usd: string;
    max_concurrent: number;
    max_exposure_usd: string;
    overfit_risk: string;
  };
}

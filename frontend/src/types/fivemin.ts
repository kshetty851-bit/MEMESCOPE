/** The Five-Minute Lab board. Shapes mirror the server; accounting is server-side. */

export interface FiveMinCycle {
  cycle_no: number;
  base_usd: number | null;
  target_usd: number | null;
  started_at: string;
  reached_at: string | null;
  equity_at_target: number | null;
  realised_equity: number | null;
  positions_closed: number | null;
  outcome: string | null;
}

export interface FiveMinPosition {
  id: string;
  mint: string;
  status: string;
  opened_at: string;
  size_usd: number | null;
  open_value: number | null;
  exec_multiple: number | null;
  exit_reason: string | null;
}

export interface FiveMinBoard {
  disclosure: string;
  activated: boolean;
  spec_version: string;
  spec_hash: string;
  strategy_id?: string;
  name?: string;
  rules?: Record<string, unknown>;
  starting_equity: number | null;
  target_multiple: number | null;
  failure_floor?: number | null;
  cash?: number | null;
  open_value?: number | null;
  equity?: number | null;
  status?: string;
  cycles_banked?: number;
  current_cycle?: {
    cycle_no: number;
    base_usd: number | null;
    target_usd: number | null;
    started_at: string;
  } | null;
  cycles: FiveMinCycle[];
  positions: FiveMinPosition[];
  /** The hold under test. */
  time_exit_minutes?: number;
  /** False by design: the stake never follows the balance. */
  sizing_scales?: boolean;
}

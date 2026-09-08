/** CPY-01 against its control, and whether the difference means anything. */

export interface CopyArm {
  role: "signal" | "control";
  present: boolean;
  strategy_id?: string;
  name?: string;
  cash?: number;
  open_value?: number;
  equity?: number;
  closed_trades?: number;
  realised_pnl?: number;
  /** The test that matters: the record with its single best trade removed. */
  realised_pnl_excluding_best?: number;
  best_trade_pnl?: number | null;
}

export type CopyVerdict =
  | "control_not_started"
  | "not_enough_data"
  | "carried_by_one_trade"
  | "control_matches_or_wins"
  | "signal_beats_control";

export interface CopyComparison {
  activated: boolean;
  since?: string;
  bar: { min_closed_trades: number; must_survive_dropping_best_trade?: boolean };
  arms: CopyArm[];
  paired_closed_trades?: number;
  verdict: CopyVerdict;
  verdict_detail?: string;
  disclosure?: string;
}

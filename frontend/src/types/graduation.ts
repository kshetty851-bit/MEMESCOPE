/** What happens in the hour after a pump.fun coin graduates. */

export interface GraduationAge {
  minutes: number;
  n: number;
  median_pct?: number;
  mean_pct?: number;
  pct_up?: number;
  worst_pct?: number;
  best_pct?: number;
}

export interface GraduationCohort {
  disclosure: string;
  cohort: number;
  total_stamped: number;
  /** Coins already graduated when the collector first looked. Their stamp is
   *  when we started watching, not when they graduated, so they are excluded. */
  excluded_cold_start: number;
  since: string | null;
  ages: GraduationAge[];
}


/** A simulated $100 book over the same cohort. Nothing is traded. */
export interface PaperHorizon {
  minutes: number;
  trades: number;
  final_equity_gross: number;
  final_equity_net: number;
  pnl_gross: number;
  pnl_net: number;
  execution_charged: number;
  /** The same book with its single best trade removed. Shown BESIDE the
   *  headline, never instead of it — on this population they disagree. */
  final_equity_without_best: number;
  pnl_without_best: number;
  best_trade_multiple: number | null;
  skipped_no_mark_yet: number;
  skipped_capacity: number;
  excluded_glitch: number;
}

export interface GraduationPaper {
  disclosure: string;
  book_usd: number;
  position_usd: number;
  max_concurrent: number;
  cohort: number;
  horizons: PaperHorizon[];
}


/** One hourly round: buy everything that graduated, close all at +60m. */
export interface CycleRound {
  hour: string;
  coins: number;
  traded: number;
  no_mark: number;
  glitched: number;
  stake_each?: number;
  opened_with: number;
  closed_with: number;
  round_multiple: number | null;
}

export interface GraduationCycles {
  disclosure: string;
  start_usd: number;
  horizon_minutes: number;
  rounds_total: number;
  rounds_traded: number;
  final_balance: number;
  /** Compounding lets one hour lift every hour after it, so this is the
   *  sequence with its single best round removed. */
  final_balance_without_best_round: number;
  best_round_multiple: number | null;
  rounds: CycleRound[];
}

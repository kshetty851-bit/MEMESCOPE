/**
 * V6 Forward Strategy Lab wire types.
 *
 * Every number arrives already computed. The client formats and sorts; it
 * never derives a figure the experiment owns, because a second implementation
 * would be a second answer and the first time either changed they would
 * disagree.
 */

export interface LabStrategyRow {
  rank: number;
  strategy_id: string;
  name: string;
  status: "active" | "failed";
  failed_reason: string | null;
  checkpoint_minutes: number | null;
  size_usd: number;
  max_concurrent: number;
  max_exposure_usd: number;
  starting_equity: number;
  cash: number;
  open_cost: number;
  open_value: number;
  equity: number;
  net_pnl: number;
  /** Return on the full $1,000 wallet — mostly idle cash. */
  return_pct: number;
  open_cost_basis: number;
  open_pnl: number;
  /** Return on the book held right now: (open value − open cost) / open cost. */
  open_return_pct: number | null;
  deployed_ever: number;
  /** Return on every dollar ever committed, realised + unrealised. */
  deployed_return_pct: number | null;
  capital_at_work_pct: number;
  trades: number;
  open_positions: number;
  wins: number;
  losses: number;
  win_pct: number | null;
  expectancy: number | null;
  profit_factor: number | null;
  max_dd_pct: number;
  avg_position: number;
  exec_125_pct: number;
  exec_150_pct: number;
  exec_200_pct: number;
  best_trade: number | null;
  worst_trade: number | null;
  expectancy_ex_best1: number | null;
  expectancy_ex_best3: number | null;
  top1_profit_share_pct: number | null;
  top3_profit_share_pct: number | null;
  losing_streak: number;
  confidence: string;
  evidence: string;
  overfit_risk: string;
  hist: Record<string, number | string>;
  hist_is_proxy: boolean;
}

export interface LabLeaders {
  profit: { strategy_id: string; name: string; equity: number; return_pct: number;
            confidence: string };
  risk_adjusted: { strategy_id: string; name: string; return_pct: number;
                   profit_factor: number | null; max_dd_pct: number; trades: number;
                   confidence: string };
  executable_2x: { strategy_id: string; name: string; exec_200_pct: number;
                   trades: number; confidence: string };
}

export interface LabRule {
  id: string;
  name: string;
  hypothesis: string;
  checkpoint_minutes: number | null;
  checkpoint_label: string;
  entry: { feature: string; op: string; value: string; reason: string; text: string }[];
  entry_text: string[];
  exits: Record<string, string | number>;
  exit_text: string[];
  size_usd: string;
  max_concurrent: number;
  max_exposure_usd: string;
  evidence: string;
  overfit_risk: string;
  hist: Record<string, number | string>;
  hist_is_proxy: boolean;
  caveats: string[];
  note: string;
}

/** A thirty-day band, resampled from a strategy's own closed trades.
 *
 * `projectable` false means the sample cannot support one — render `reason`,
 * never a number. The random control is always served alongside the leader,
 * because a band that beats zero but not blind entry has shown nothing. */
export interface LabProjection {
  strategy_id: string;
  name: string;
  equity_now: string;
  projectable: boolean;
  reason: string;
  trades_observed: number;
  trades_per_day: number;
  projected_trades: number;
  horizon_days: number;
  p10: string | null;
  p50: string | null;
  p90: string | null;
  p_profit: number | null;
  p_ruin: number | null;
  notes: string[];
}

export interface LabBoard {
  disclosure: string;
  spec_version: string;
  spec_hash: string;
  spec_immutable: boolean;
  /** The book each strategy starts with. Served so the page cannot hardcode it. */
  starting_equity: number;
  valid_from: string;
  snapshot_at: string;
  snapshot_taken: boolean;
  snapshot_taken_at: string | null;
  elapsed_hours: number;
  hours_to_snapshot: number;
  status: string;
  real_money_enabled: boolean;
  total_closed_trades: number;
  overall_confidence: string;
  leaders: LabLeaders;
  projection?: {
    leader?: LabProjection;
    random_control?: LabProjection;
  };
  strategies: LabStrategyRow[];
  rulebook: LabRule[];
}

export interface LabPositionRow {
  /** Needed to target a manual close. */
  id: string;
  mint: string;
  opened_at: string;
  status: string;
  size_usd: number;
  open_value: number | null;
  exec_multiple: number | null;
  peak_exec_multiple: number;
  closed_at: string | null;
  exit_reason: string | null;
  exit_proceeds_usd: number | null;
  pnl: number | null;
  route_state: string | null;
  reached_125: boolean;
  reached_150: boolean;
  reached_200: boolean;
  partial_done: boolean;
}

export interface LabStrategyDetail {
  disclosure: string;
  strategy: {
    id: string; name: string; hypothesis: string;
    checkpoint_minutes: number | null;
    entry: { feature: string; op: string; value: string; reason: string }[];
    size_usd: string; max_concurrent: number; max_exposure_usd: string;
    exits: Record<string, string | number>;
    evidence: string; overfit_risk: string;
    hist: Record<string, number | string>; hist_is_proxy: boolean;
    caveats: string[]; note: string;
  };
  stats: LabStrategyRow;
  historical_warning: string | null;
  skip_reasons: Record<string, number>;
  decisions_total: number;
  equity_curve: { at: string; equity: number; cash: number; open_value: number }[];
  positions: LabPositionRow[];
}

export interface LabTrade {
  /** Needed to target a manual close. */
  id: string;
  strategy_id: string;
  strategy_name: string | null;
  /** The full contract address, never truncated — this view exists so it can be copied. */
  mint: string;
  symbol: string | null;
  token_name: string | null;
  status: "open" | "closed";
  opened_at: string;
  closed_at: string | null;
  held_hours: number;
  size_usd: number;
  entry_price: number;
  entry_liquidity_usd: number | null;
  current_value_usd: number | null;
  unrealised_pnl: number | null;
  realised_pnl: number | null;
  exec_multiple: number | null;
  peak_exec_multiple: number;
  exit_reason: string | null;
  exit_proceeds_usd: number | null;
  route_state: string | null;
  reached_125: boolean;
  reached_150: boolean;
  reached_200: boolean;
  partial_done: boolean;
  entry_source: string;
}

export interface LabTrades {
  disclosure: string;
  total: number;
  open: number;
  closed: number;
  trades: LabTrade[];
}

/** One immutable leaderboard, frozen at a boundary and never rewritten. */
export interface LabSnapshot {
  label: string;
  boundary_at: string;
  taken_at: string;
  elapsed_hours: number;
  payload: {
    spec_version?: string;
    spec_hash?: string;
    total_closed_trades?: number;
    overall_confidence?: string;
    strategies?: LabStrategyRow[];
  };
}

export interface LabSnapshots {
  disclosure: string;
  snapshots: LabSnapshot[];
}

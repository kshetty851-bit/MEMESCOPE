/**
 * V5 Forward Strategy Arena types.
 *
 * RESEARCH SIMULATION. Arena equity is not Paper Wallet equity and the two are
 * never rendered as the same figure. Money arrives as strings and stays that
 * way until display, per the platform's decimal rule.
 */

export interface ArenaCandidate {
  code: string;
  name: string;
  version: string;
  status: string;
  failed_reason: string | null;
  starting_equity: string;
  equity: string;
  cash: string;
  deployed: string;
  realized_pnl: string;
  total_return: string;
  trades: number;
  wins: number;
  losses: number;
  /** null until a trade closes — an unmeasured rate is not a zero rate. */
  win_rate: string | null;
  win_rate_ci_low: string | null;
  win_rate_ci_high: string | null;
  expectancy: string | null;
  profit_factor: string | null;
  avg_win: string | null;
  avg_loss: string | null;
  max_drawdown: string;
  open_positions: number;
  skipped: number;
  buy_failures: number;
  sell_failures: number;
  route_unknown: number;
  reached_125: number;
  reached_150: number;
  reached_200: number;
}

export interface ArenaBoard {
  candidates: ArenaCandidate[];
  checkpoint_minutes: number;
  rules_version: string;
  valid_from: string | null;
  disclosure: string;
  observed_at: string;
}

export interface ArenaDecision {
  code: string;
  mint_address: string;
  checkpoint_at: string;
  eligible: boolean;
  skip_reason: string | null;
  route_state: string | null;
  features: Record<string, unknown> | null;
}

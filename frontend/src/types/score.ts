/**
 * AI scoring API contracts.
 *
 * Mirrors `backend/app/schemas/score.py`. Every numeric field arrives as a
 * **string**: the backend serialises `Decimal` that way so a JSON float cannot
 * silently round the numbers the score's waterfall has to reconcile. Parse at
 * the edge of rendering with `num()`, never store the parsed value.
 */

export type ScoreGrade = "critical" | "weak" | "watch" | "strong" | "high_conviction";

/** Why a score is absent. `scored` is the only state with a body. */
export type ScoreStatus =
  "scored" | "awaiting_market" | "not_scored" | "insufficient_data" | "scoring_disabled";

export type ReasonSeverity = "info" | "positive" | "caution" | "critical";

export interface ScoreReason {
  code: string;
  severity: ReasonSeverity;
  /** Which AI division owns this readout. */
  agent: string;
  /** Rendered by the backend from the code — never composed on the client. */
  message: string;
}

export interface ScoreComponent {
  id: string;
  agent: string;
  available: boolean;
  score: string | null;
  declared_weight: string;
  effective_weight: string;
  contribution: string;
  raw: Record<string, string | null>;
  reasons: string[];
}

export interface EvidenceSummary {
  /** 0–100. Coverage times observation depth. Time-invariant, stored. */
  evidence: string;
  /** 0–100. Share of the model's weight that could be applied. */
  coverage: string;
  observations: number;
  /** 0–1. Derived per request from the age of the underlying snapshot. */
  freshness: string;
  /** 0–100. Evidence discounted by freshness. */
  confidence: string;
}

export interface RiskSummary {
  /** 0–100. Higher is more dangerous. */
  market_risk: string;
  /** The risk gate capped the score outright. */
  has_veto: boolean;
  deduction: string;
}

export interface TokenScore {
  mint_address: string;
  score: string;
  opportunity_raw: string;
  grade: ScoreGrade;
  is_elite: boolean;
  evidence: EvidenceSummary;
  risk: RiskSummary;
  model_version: string;
  evaluated_at: string;
  latest_snapshot_at: string | null;
  previous_score: string | null;
  last_trigger: string | null;
  /** Empty on ranking rows; populated on the per-token endpoint. */
  components: ScoreComponent[];
  reasons: ScoreReason[];
}

export interface TokenScoreEnvelope {
  mint_address: string;
  status: ScoreStatus;
  score: TokenScore | null;
}

export interface ScoreHistoryEntry {
  evaluated_at: string;
  score: string;
  delta: string | null;
  trigger: string;
  grade: ScoreGrade;
  is_elite: boolean;
  has_veto: boolean;
  evidence: string;
  coverage: string;
  market_risk: string;
  opportunity_raw: string;
  observations: number;
  model_version: string;
  reasons: ScoreReason[];
}

export interface ScoreHistoryPage {
  mint_address: string;
  items: ScoreHistoryEntry[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface TopScoreEntry {
  token: { mint_address: string; name: string | null; symbol: string | null };
  score: TokenScore;
}

export interface TopScorePage {
  items: TopScoreEntry[];
  total: number;
  candidate_total: number;
  page: number;
  page_size: number;
  pages: number;
  applied_filters: Record<string, unknown>;
}

export interface ModelComponent {
  id: string;
  agent: string;
  weight: string;
  /** False for signals whose data source does not exist yet. */
  available: boolean;
}

export interface ScoringModel {
  version: string;
  risk_lambda: string;
  veto_ceiling: string;
  max_single_contribution: string;
  min_scorable_weight: string;
  declared_weight_total: string;
  /** Ceiling on coverage, and therefore evidence, for this model. */
  available_weight_total: string;
  components: ModelComponent[];
  grade_bands: { grade: ScoreGrade; lower_bound: string; upper_bound: string | null }[];
  elite_gate: {
    min_score: string;
    min_evidence: string;
    max_risk_penalty: string;
    min_liquidity_usd: string;
    sustain_evaluations: number;
    reachable: boolean;
  };
  scoring_enabled: boolean;
}

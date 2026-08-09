/**
 * Opportunity board API contracts.
 *
 * Mirrors `backend/app/opportunities/schemas.py`. Every numeric field arrives
 * as a **string** — the backend serialises `Decimal` that way so a JSON float
 * cannot silently round a figure. Parse at the edge of rendering with `num()`,
 * never store the parsed value.
 */

export type OpportunityStatus =
  | "new"
  | "pending_confirmation"
  | "active"
  | "expiring"
  | "closed"
  | "archived";

export type OpportunityStage =
  | "unknown"
  | "pre_graduation"
  | "near_graduation"
  | "fresh_graduation"
  | "established";

export type PriorityBand = "low" | "medium" | "high" | "critical";

export type SignalSeverity = "info" | "notable" | "major" | "critical";

export interface OpportunityEvidence {
  label: string;
  value: string;
  detail: string | null;
}

/**
 * Rendered by the backend, in the five parts of AD-07. The client displays
 * these verbatim and never composes them — a second opinion about the same
 * token, written client-side, can disagree with the engine that produced it.
 */
export interface OpportunityExplanation {
  headline: string;
  trigger: string;
  boundary: string | null;
  delta: string[];
  corroboration: string[];
  /** What could *not* be checked. Never hidden; this is the honesty clause. */
  limits: string[];
}

export interface OpportunitySignal {
  signal_type: string;
  provider: string;
  status: string;
  severity: SignalSeverity;
  /** The provider's claim about the transition, 0–100. */
  strength: string;
  /** What the engine derived from it. Never exceeds strength. */
  confidence: string;
  confirmations: number;
  observations: number;
  detected_at: string;
  last_confirmed_at: string;
  expires_at: string;
  expires_in_seconds: number;
  reason_codes: string[];
  evidence: OpportunityEvidence[];
  explanation: OpportunityExplanation;
}

export interface Opportunity {
  mint_address: string;
  name: string | null;
  symbol: string | null;
  image_url?: string | null;
  generation: number;
  status: OpportunityStatus;
  stage: OpportunityStage;
  priority: string;
  priority_band: PriorityBand;
  confidence: string;
  detected_at: string;
  last_confirmed_at: string;
  /** How long ago the ranking was last recomputed. Surfaced, not hidden. */
  confirmed_age_seconds: number;
  signals: OpportunitySignal[];
}

/**
 * No `total`, by design: an unconditional count alongside the page is
 * measurable cost for a question nobody asks of a live board.
 */
export interface OpportunityBoard {
  items: Opportunity[];
  page: number;
  page_size: number;
  has_more: boolean;
  applied_filters: {
    signal_type: string | null;
    stage: string | null;
    /** False when the engine's feature flag is off. Empty, not absent. */
    engine_enabled: boolean;
  };
  observed_at: string;
}

import { api } from "@/lib/api-client";

/**
 * PIPELINE HEALTH, AS THE BACKEND ACTUALLY PUBLISHES IT.
 *
 * Mirrors `backend/app/health/schemas.py` at the field level. Nothing is
 * renamed on the way in: a rename here would put a translation step somewhere
 * nobody looks, and the whole point of the adapter is that the translation
 * happens in exactly one place that has tests.
 *
 * Lives under `lib/hq` rather than `types/` because HQ is the only consumer.
 * When a second screen wants pipeline health it can move; until then, keeping
 * it here is what stops the type from being imported into a bundle that has no
 * use for it.
 *
 * WHAT THIS ENDPOINT DOES ON FAILURE
 *
 * `GET /api/v1/health/pipeline` answers 503 when its own roll-up is `down`,
 * with the full body attached. The shared API client turns any non-2xx into an
 * `ApiError` and discards the body, so HQ cannot read which stage failed — a
 * down pipeline arrives as a failed request and every pipeline-backed employee
 * reads UNKNOWN. That is under-reporting, not mis-reporting, so it satisfies
 * the truthfulness rule; it is recorded as a known gap rather than worked
 * around by giving HQ its own fetch path.
 */

export type StageStatus = "healthy" | "degraded" | "down";

export interface ScannerHealth {
  status: StageStatus;
  last_discovery: string | null;
  minutes_since_last_token: number | null;
  reconnect_attempts: number | null;
  failure_reason: string | null;
}

export interface EnrichmentHealth {
  status: StageStatus;
  last_snapshot: string | null;
  minutes_since_last_snapshot: number | null;
  queue_depth: number;
  dead_lettered: number;
  priority_queue_depth: number;
  priority_tokens: number;
  oldest_priority_wait_seconds: number | null;
  oldest_normal_wait_seconds: number | null;
  tracked_freshness_p50_seconds: number | null;
  tracked_freshness_p95_seconds: number | null;
  tracked_freshness_worst_seconds: number | null;
  /**
   * Tracked tokens whose newest snapshot is older than the backend's stale
   * threshold.
   *
   * The backend reports this but — as of the contract read for HQ-4 — does not
   * let it degrade `status`, which is classified purely from how long ago the
   * last snapshot landed anywhere. So a lane can be delivering nothing to the
   * tokens on screen while the stage still reports `healthy`. HQ reads the
   * count directly for exactly that reason.
   */
  tracked_stale_count: number;
}

export interface ScoringHealth {
  status: StageStatus;
  last_score: string | null;
  minutes_since_last_score: number | null;
  pending: number;
}

export interface RadarStageHealth {
  status: StageStatus;
  last_cycle: string | null;
  minutes_since_last_cycle: number | null;
  tracked_tokens: number;
}

export interface PipelineHealth {
  scanner: ScannerHealth;
  market_enrichment: EnrichmentHealth;
  scoring: ScoringHealth;
  radar: RadarStageHealth;
  overall: StageStatus;
  environment: string;
  version: string;
  observed_at: string;
}

export function fetchPipelineHealth(): Promise<PipelineHealth> {
  return api.get<PipelineHealth>("/health/pipeline");
}

/**
 * `GET /real-wallet-safety/evaluations/{mint}`.
 *
 * Read-only audit view of the Real Wallet's own preview safety gate — the
 * *only* real per-mint safety evidence anywhere in the API. It does not
 * gate Paper Wallet's entry decision; see `case-file.ts`'s module header
 * for why. Fetched only for a currently visible packet or an explicitly
 * opened case file — never for a whole page of tokens at once.
 */
export interface SafetyEvaluationRow {
  decision: string;
  evaluated_at: string;
  trade_size_usd: string;
  policy_version: string;
  reason_codes: string[];
  market_snapshot_at: string | null;
  market_age_seconds: string | null;
  buy_price_impact_pct: string | null;
  sell_price_impact_pct: string | null;
  round_trip_loss_usd: string | null;
  round_trip_loss_pct: string | null;
  provenance: string | null;
  token_configuration: Record<string, unknown> | null;
}

export interface SafetyEvaluations {
  mint_address: string;
  items: SafetyEvaluationRow[];
}

export function fetchSafetyEvaluations(mint: string): Promise<SafetyEvaluations> {
  return api.get<SafetyEvaluations>(`/real-wallet-safety/evaluations/${mint}`);
}

/**
 * `GET /token-security/summary` — HQ-6.
 *
 * Atlas's first real source. Read-only, and deliberately independent of
 * `REAL_WALLET_EXECUTION_MODE`: HQ-5 found the only per-mint security
 * evidence in the platform was written by the Real Wallet's dry-run preview,
 * so a disabled wallet meant HQ could say nothing about any token's safety.
 * Token security is a property of the token.
 *
 * `source_state` is the field that matters and it is computed server-side:
 *
 *   `no_evaluations` — nothing has ever been evaluated. Real zeros.
 *   `stale`          — evidence exists but is older than its own window.
 *   `live`           — current.
 *
 * A zero count with `no_evaluations` is NOT a clean bill of health, and the
 * adapter must never render it as one.
 */
export interface TokenSecuritySummary {
  window_hours: number;
  evaluator_version: string;
  evaluated_recently: number;
  verified_count: number;
  failed_count: number;
  unknown_count: number;
  failures_by_reason: Record<string, number>;
  last_evaluation_at: string | null;
  total_evaluations: number;
  source_state: "no_evaluations" | "stale" | "live";
  observed_at: string;
}

export function fetchTokenSecuritySummary(): Promise<TokenSecuritySummary> {
  return api.get<TokenSecuritySummary>("/token-security/summary");
}

/** One check inside a shared security evaluation. */
export interface TokenSecurityCheck {
  name: string;
  status: "PASS" | "FAIL" | "UNKNOWN" | "NOT_APPLICABLE";
  reason_codes: string[];
  detail: string;
  evidence: Record<string, unknown>;
}

export interface TokenSecurityEvaluation {
  mint_address: string;
  evaluated_at: string;
  overall_status: "VERIFIED" | "FAILED" | "UNKNOWN";
  evaluator_version: string;
  market_snapshot_at: string | null;
  reason_codes: string[];
  checks: TokenSecurityCheck[];
  evidence: Record<string, unknown>;
  stale: boolean;
  stale_checks: string[];
}

export interface TokenSecurityEvaluations {
  mint_address: string;
  evaluator_version: string;
  items: TokenSecurityEvaluation[];
}

export function fetchTokenSecurity(mint: string): Promise<TokenSecurityEvaluations> {
  return api.get<TokenSecurityEvaluations>(`/token-security/evaluations/${mint}`);
}

/**
 * `GET /paper/decisions/{mint}` — the engine's own per-mint verdict.
 *
 * HQ-5 could never render DECISION FAILED because refusals were counted in
 * aggregate and discarded per mint. This is the read-back of the decision the
 * review pass records at the moment it decides. HQ does not, and must not,
 * recompute eligibility from it.
 */
export interface PaperDecisionRow {
  decision: string;
  decided_at: string;
  source: string;
  wallet_code: string;
  strategy_id: string;
  strategy_version: string;
  reason_codes: string[];
  reason_labels: string[];
  /** SEC-2: the entry gate's own classification, when it made the decision. */
  entry_outcome: EntryOutcome | null;
  security_status: "VERIFIED" | "FAILED" | "UNKNOWN" | null;
  security_evaluated_at: string | null;
  security_evaluator_version: string | null;
}

/**
 * SEC-2 entry-gate outcomes, as the backend classifies them.
 *
 * `REFUSED_UNAVAILABLE` is the one that must never be rendered as a statement
 * about the token: it means the platform could not look, not that anything is
 * wrong. See `app/security/entry_policy.py`.
 */
export type EntryOutcome =
  | "ALLOWED"
  | "REFUSED_UNSAFE"
  | "REFUSED_UNKNOWN"
  | "REFUSED_UNAVAILABLE";

export interface PaperDecisions {
  mint_address: string;
  items: PaperDecisionRow[];
}

export function fetchPaperDecisions(mint: string): Promise<PaperDecisions> {
  return api.get<PaperDecisions>(`/paper/decisions/${mint}`);
}

/**
 * `GET /real-wallet-safety/execution-posture` — the Execution Vault's source.
 *
 * Read-only by construction: the endpoint reports whether execution *could*
 * happen and exposes nothing that would help anyone make it happen. There is
 * no balance, no key, no signer detail and no verb but GET.
 *
 * The backend collapses the flags into one state, most-restrictive-wins, so
 * HQ cannot assemble an optimistic reading out of individually true parts.
 */
export type VaultState = "HALTED" | "LOCKED" | "ARMED" | "UNLOCKED" | "UNKNOWN";

export interface KillSwitchRow {
  kind: string;
  active: boolean;
  reason: string | null;
  activated_at: string | null;
}

export interface ExecutionPosture {
  state: VaultState;
  detail: string;
  mode?: string;
  execution_enabled?: boolean;
  autotrade_enabled?: boolean;
  network?: string;
  kill_switches?: KillSwitchRow[];
  active_kill_switches?: number;
  observed_at: string;
  sourced: boolean;
}

export function fetchExecutionPosture(): Promise<ExecutionPosture> {
  return api.get<ExecutionPosture>("/real-wallet-safety/execution-posture");
}

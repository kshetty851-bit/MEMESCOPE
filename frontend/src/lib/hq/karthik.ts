import { api } from "@/lib/api-client";

/**
 * THE KARTHIK SURFACE, AS THE BACKEND PUBLISHES IT.
 *
 * Mirrors `backend/app/karthik/schemas.py` field for field, for the same
 * reason `operations.ts` mirrors `hq_ops/schemas.py`: nothing is renamed on
 * the way in, so the only translation between the wallet's vocabulary and the
 * office's happens in `adapter.ts`, which has tests.
 *
 * ── `measured` IS THE FIELD THAT MATTERS ────────────────────────────────
 *
 * Every screen carries one. A screen with `measured: false` has nothing to
 * render but its `detail`, and rendering its empty `values` as zeroes is the
 * specific failure this whole feature is built to avoid. The panel therefore
 * branches on `measured` before it touches `values`, never the other way
 * round.
 *
 * ── MONEY IS A STRING ───────────────────────────────────────────────────
 *
 * Prices are stored to eighteen decimal places and a JSON number would round
 * them. Nothing here parses one into a float for display; the panel formats
 * the string.
 */

export type BindingState = "bound" | "unbound" | "forbidden" | "designated_but_missing";

export interface ScreenReading {
  measured: boolean;
  detail: string;
  values: Record<string, unknown>;
  rows: Array<Record<string, unknown>>;
}

export interface WalletBinding {
  state: BindingState;
  designated_strategy_id: string;
  detail: string;
  /** True only when a real wallet row is behind this. Gate every figure on it. */
  readable: boolean;
  /** True when the binding itself is something only the owner can fix. */
  needs_owner: boolean;
  wallet_id: string | null;
  strategy_version: string | null;
  generation: number | null;
  starting_balance: string | null;
  started_at: string | null;
  archived_at: string | null;
}

export interface IntegrityDeduction {
  factor: string;
  label: string;
  penalty: number;
  measured: boolean;
  detail: string;
}

export interface ExperimentIntegrity {
  /** `null` when nothing could be measured. Never render this as 0 or 100. */
  score: number | null;
  band: "HEALTHY" | "DEGRADED" | "UNRELIABLE" | "NOT MEASURED";
  headline: string;
  deductions: IntegrityDeduction[];
  unmeasured: number;
}

export interface KarthikAction {
  at: string;
  agent: string;
  action: string;
  /** `allowed` | `observe_only` | `not_allowlisted`. */
  autonomy: string;
  reason: string;
  outcome: string;
  preconditions: Record<string, unknown>;
  result: Record<string, unknown>;
  verification: Record<string, unknown>;
}

export interface KarthikIncident {
  code: string;
  kind: "karthik_incident" | "karthik_approval" | "karthik_observation";
  component: string;
  severity: "info" | "degraded" | "critical";
  status: string;
  autonomy: string;
  agent: string | null;
  signature: string;
  symptoms: Record<string, unknown>;
  root_cause: string | null;
  owner_rationale: string | null;
  detected_at: string;
  resolved_at: string | null;
  actions: KarthikAction[];
}

export interface SafeRepairInfo {
  key: string;
  summary: string;
  precondition: string;
  reversible: boolean;
}

export interface DefectCheck {
  key: string;
  label: string;
  rectification: "AUTO_FIX" | "OWNER_REQUIRED" | "OBSERVE_ONLY";
  severity: string;
  detectable: boolean;
  gap: string | null;
}

export interface KarthikReport {
  window: string;
  since: string | null;
  until: string;
  measured: boolean;
  detail: string;
  starting_equity_usd: string | null;
  ending_equity_usd: string | null;
  pnl_usd: string | null;
  opportunities: number | null;
  entered: number | null;
  targets_hit: number | null;
  dead_zero: number | null;
  open_positions: number | null;
  closed_positions: number | null;
  best_trade: Record<string, unknown> | null;
  worst_trade: Record<string, unknown> | null;
  average_hold_seconds: number | null;
  target_hit_rate: number | null;
  dead_rate: number | null;
  cash_utilisation: number | null;
  bugs_detected: number | null;
  repairs_performed: number | null;
  owner_attention: number | null;
  integrity: Record<string, unknown> | null;
  daily_series: Array<Record<string, unknown>>;
}

export interface WhileAwaySummary {
  since: string | null;
  until: string;
  measured: boolean;
  detail: string;
  opportunities: number | null;
  new_trades: number | null;
  targets_hit: number | null;
  dead_positions: number | null;
  pnl_usd: string | null;
  biggest_winner: Record<string, unknown> | null;
  biggest_loss: Record<string, unknown> | null;
  bugs_found: number | null;
  bugs_fixed: number | null;
  owner_attention: number | null;
  integrity_score: number | null;
}

/** The six monitors in Karthik Lab, named as §4 names them. */
export interface KarthikScreens {
  wallet: ScreenReading;
  feed: ScreenReading;
  positions: ScreenReading;
  targets: ScreenReading;
  health: ScreenReading;
  reports: ScreenReading;
}

export interface KarthikState {
  binding: WalletBinding;
  /**
   * Published rather than inferred. A panel that guessed this would either
   * claim repairs that cannot happen or hide ones that can.
   */
  autonomy: "OBSERVE_ONLY" | "SAFE_AUTOREPAIR";
  screens: KarthikScreens;
  accounting: ScreenReading;
  integrity: ExperimentIntegrity;
  incidents: KarthikIncident[];
  recent: KarthikIncident[];
  actions: KarthikAction[];
  allowlist: SafeRepairInfo[];
  checks: DefectCheck[];
  reports: Record<string, KarthikReport>;
  while_away: WhileAwaySummary;
  observed_at: string;
}

/**
 * Where the browser remembers the reader's previous visit.
 *
 * Local storage rather than a server-side session: §13 asks "since your
 * previous visit", and the alternative is a per-user visit table, which is a
 * tracking feature nobody asked for in order to caption a cartoon panel. The
 * consequence is honest and worth stating — the summary is per-device, and a
 * first visit says so rather than silently showing 24 hours.
 */
export const LAST_VISIT_KEY = "memescope.hq.karthik.lastVisit";

/** The stamp to send as `?since=`, or `null` on a first visit here. */
export function readLastVisit(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LAST_VISIT_KEY);
    if (!raw) return null;
    // A corrupted or hand-edited value must not become a query parameter.
    return Number.isNaN(new Date(raw).getTime()) ? null : raw;
  } catch {
    // Storage can throw in private modes and under strict site settings.
    // Losing the "while you were away" window is a smaller failure than the
    // page not rendering, so this degrades to a first visit.
    return null;
  }
}

export function writeLastVisit(at: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LAST_VISIT_KEY, at);
  } catch {
    /* see readLastVisit */
  }
}

/**
 * `GET /api/v1/karthik-ops`. One request for the whole operational picture.
 *
 * Not `/karthik`, which is the wallet's own surface. This is the layer that
 * says whether the experiment is being run properly, and it must never be able
 * to shadow the endpoint that says what the experiment did.
 */
export function fetchKarthik(since: string | null): Promise<KarthikState> {
  return api.get<KarthikState>(
    since ? `/karthik-ops?since=${encodeURIComponent(since)}` : "/karthik-ops",
  );
}

/** Statuses that mean a finding is still live. Mirrors the backend's set. */
export const OPEN_KARTHIK_STATUSES: ReadonlySet<string> = new Set([
  "open",
  "investigating",
  "repairing",
  "verifying",
  "awaiting_owner",
]);

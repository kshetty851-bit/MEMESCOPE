import { api } from "@/lib/api-client";

/**
 * HQ OPERATIONS, AS THE BACKEND ACTUALLY PUBLISHES IT.
 *
 * Mirrors `backend/app/hq_ops/schemas.py` at the field level, for the same
 * reason `pipeline.ts` does: nothing is renamed on the way in, so the only
 * translation between MEMESCOPE's vocabulary and the office's happens in
 * `adapter.ts`, which has tests.
 *
 * ── THE FIELD THAT MATTERS MOST IS `measured` ───────────────────────────
 *
 * Every component carries a status *and* a separate `measured` flag, because
 * "we looked and it is fine" and "we could not look" are different answers.
 * The adapter must never render the second as the first — and the reason this
 * type keeps them apart rather than folding the second into a `"unknown"`
 * status is that a component can be `unknown` for reasons worth distinguishing
 * in a sentence, which `detail` carries.
 */

export type ComponentStatus = "healthy" | "degraded" | "down" | "unknown";

export interface ComponentHealth {
  component: string;
  status: ComponentStatus;
  detail: string;
  latency_ms: number | null;
  measured: boolean;
}

export interface DiskHealth {
  status: ComponentStatus;
  percent_used: number | null;
  warning_percent: number;
  critical_percent: number;
  measured: boolean;
  detail: string;
}

export interface WorkerHealth {
  status: ComponentStatus;
  nodes: string[];
  replies: number;
  measured: boolean;
  detail: string;
}

export interface SchedulerHealth {
  status: ComponentStatus;
  last_beat: string | null;
  seconds_since_beat: number | null;
  expected_within_seconds: number;
  measured: boolean;
  detail: string;
}

export interface QueueHealth {
  status: ComponentStatus;
  depths: Record<string, number>;
  total: number | null;
  measured: boolean;
  detail: string;
}

/**
 * The Strategy Lab's own row. Served by the backend since the probe was
 * written; typed here when Karthik was given the Lab watch and his desk needed
 * to show whether the tournament is still trading.
 *
 * Every field is optional because `measured: false` is a real reading — the
 * probe opens its own session and can fail — and the desk has to render "could
 * not be read" as distinct from zero. A missing count is not a quiet nil.
 */
export interface LabHealthRow {
  measured: boolean;
  detail: string;
  open_positions?: number | null;
  stale_positions?: number | null;
  stale_pct?: number | null;
  quote_backed_pct?: number | null;
  minutes_since_decision?: number | null;
  minutes_since_close?: number | null;
}

export interface OperationsHealth {
  disk: DiskHealth;
  redis: ComponentHealth;
  database: ComponentHealth;
  worker: WorkerHealth;
  scheduler: SchedulerHealth;
  queues: QueueHealth;
  /** Optional: older payloads predate the Lab probe. */
  lab?: LabHealthRow;
  overall: ComponentStatus;
  unmeasured: number;
  environment: string;
  version: string;
  observed_at: string;
}

/** One row of the autonomous audit trail. */
export interface IncidentAction {
  at: string;
  agent: string;
  action: string;
  autonomy: string;
  reason: string;
  outcome: "attempted" | "skipped" | "succeeded" | "failed" | "rolled_back";
  preconditions: Record<string, unknown>;
  result: Record<string, unknown>;
  verification: Record<string, unknown>;
}

export interface Incident {
  code: string;
  kind: "incident" | "investigation" | "approval";
  component: string;
  severity: "info" | "degraded" | "critical";
  status:
    | "open"
    | "investigating"
    | "repairing"
    | "verifying"
    | "awaiting_owner"
    | "resolved"
    | "failed";
  autonomy: "green" | "yellow" | "red";
  agent: string | null;
  signature: string;
  symptoms: Record<string, unknown>;
  root_cause: string | null;
  owner_rationale: string | null;
  detected_at: string;
  resolved_at: string | null;
  actions: IncidentAction[];
}

/**
 * One entry of the backend's allowlist.
 *
 * Published by the API rather than restated here. That is deliberate: a
 * hard-coded copy in the frontend could claim HQ is permitted to do something
 * the backend would refuse, and a panel that overstates what a system can do
 * is the exact failure mode this whole feature is built to avoid.
 */
export interface RemediationInfo {
  key: string;
  autonomy: string;
  agent: string;
  summary: string;
  reversible: boolean;
}

export interface HqOperations {
  health: OperationsHealth;
  incidents: Incident[];
  recent: Incident[];
  activity: IncidentAction[];
  allowlist: RemediationInfo[];
  /** False when HQ detects and records but executes nothing. */
  autonomy_enabled: boolean;
  invariants: { digest?: string; values?: Record<string, unknown> };
}

/** `GET /api/v1/hq`. One request for the whole operational picture. */
export function fetchHqOperations(): Promise<HqOperations> {
  return api.get<HqOperations>("/hq");
}

/** Statuses that mean an incident is still live. Mirrors `OPEN_STATUSES`. */
export const OPEN_INCIDENT_STATUSES: ReadonlySet<Incident["status"]> = new Set([
  "open",
  "investigating",
  "repairing",
  "verifying",
  "awaiting_owner",
]);

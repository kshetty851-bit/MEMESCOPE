import { api } from "@/lib/api-client";
import type { EmployeeId } from "./employees";

/**
 * ONE DESK'S LAST 24 HOURS, AS THE BACKEND PUBLISHES IT.
 *
 * Mirrors `backend/app/hq_ops/desk.py` field for field. Nothing is renamed on
 * the way in and nothing is defaulted: `measured` is the field the panel
 * branches on, and a client-side `?? 0` here would erase the one distinction
 * the endpoint exists to make.
 *
 * ── WHY `measured` IS FALSE FOR MOST DESKS ──────────────────────────────
 *
 * Ten of the fourteen report a sampled gauge — a disk percentage, a queue
 * depth, a roll-up of other people's readings — and a gauge has no history.
 * Those desks return `measured: false` with a sentence saying what would have
 * to exist for them to have one, which tells a reader whether the desk was
 * quiet or whether nobody was writing anything down. They are different facts.
 */

export interface DeskCount {
  label: string;
  value: number;
  source: string;
}

export interface DeskEvent {
  at: string;
  label: string;
  detail: string;
  kind: "action" | "incident" | "trade" | "admission";
}

/** A figure whose value is not a count: money, a percentage, a duration. */
export interface DeskReading {
  label: string;
  value: string;
  source: string;
}

/**
 * What a desk has to say about its own record.
 *
 * `lever` is the field that carries this feature's whole discipline: it names
 * a quantity that would have to MOVE, never an outcome that would follow.
 * "Execution costs 54% of the available move" is a lever; "widen the stop and
 * it turns positive" is a forecast, and the backend's tests refuse to emit
 * one. Rendered as given — the panel restates nothing.
 */
export interface DeskFinding {
  headline: string;
  evidence: string;
  lever: string;
  source: string;
}

export interface DeskDossier {
  employee: string;
  since: string;
  until: string;
  measured: boolean;
  detail: string;
  headline: string;
  sources: string[];
  counts: DeskCount[];
  timeline: DeskEvent[];
  /** Absent on desks that predate the analysts; defaulted at the use site. */
  readings?: DeskReading[];
  findings?: DeskFinding[];
}

/** `GET /api/v1/hq/desk/{employee}`. Read on demand — nobody needs fourteen
 *  dossiers to draw the room. */
export function fetchDeskDossier(employee: EmployeeId): Promise<DeskDossier> {
  return api.get<DeskDossier>(`/hq/desk/${employee}`);
}

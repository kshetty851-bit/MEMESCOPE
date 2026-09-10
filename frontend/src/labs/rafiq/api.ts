import { api } from "@/lib/api-client";

import type {
  RafiqBreaker,
  RafiqPosition,
  RafiqStatus,
  RafiqTrade,
} from "./types";

/**
 * RAFIQ LAB CLIENT
 *
 * Fetches and nothing else. **It never decides.** Every figure — equity, the
 * stop distance, the halt reason, the return — arrives already computed. A
 * threshold applied here would be a second, unpublished rule competing with
 * the one the lab actually followed, and the two would disagree the first
 * time either changed.
 *
 * There is no write. The lab trades on its own tick: no manual entry, no
 * manual exit, no activation endpoint.
 */

export const fetchRafiqStatus = () => api.get<RafiqStatus>("/labs/rafiq/status");
export const fetchRafiqPositions = () =>
  api.get<RafiqPosition[]>("/labs/rafiq/positions");
export const fetchRafiqTrades = () => api.get<RafiqTrade[]>("/labs/rafiq/trades");
export const fetchRafiqBreaker = () => api.get<RafiqBreaker[]>("/labs/rafiq/breaker");

/** Server codes, rendered here, never composed. */
export const EXIT_LABELS: Record<string, string> = {
  stop: "Stop",
  take_profit: "Take profit",
  trailing: "Trailing",
  max_hold: "Max hold",
};

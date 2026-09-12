import { api } from "@/lib/api-client";

import type { GraduationStatus, PaperBook } from "./types";

/**
 * GRADUATION LAB CLIENT
 *
 * Fetches and nothing else. Every figure arrives already computed — the
 * funnel, the signal split, the derived RPC rate. There is no write: the lab
 * records on its own tick and the backend router has no non-GET route.
 */
export function fetchStatus(): Promise<GraduationStatus> {
  return api.get<GraduationStatus>("/labs/graduation/status");
}

/**
 * Every closed trade, not the handful `/status` carries. Its own call because
 * the board polls status every thirty seconds and this list only grows.
 */
export function fetchPaperTrades(): Promise<PaperBook> {
  return api.get<PaperBook>("/labs/graduation/paper/trades");
}

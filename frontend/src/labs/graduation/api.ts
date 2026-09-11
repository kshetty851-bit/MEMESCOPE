import { api } from "@/lib/api-client";

import type { GraduationStatus } from "./types";

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

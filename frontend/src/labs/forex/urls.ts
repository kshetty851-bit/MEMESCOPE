import { API_V1 } from "@/lib/env";

/**
 * Kept out of `api.ts` on purpose: the page tests `vi.mock("./api")`, which
 * would turn a URL builder into a function returning `undefined` and the
 * export link into a dead anchor that no test would notice.
 *
 * The browser follows this link itself (a download, not a fetch), so it must be
 * the absolute `/api/v1` path the proxy serves, built from the same base the
 * API client uses.
 */
export function tradesCsvUrl(runId: number): string {
  return `${API_V1}/labs/forex/runs/${runId}/trades.csv`;
}

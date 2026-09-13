import { api } from "@/lib/api-client";

import type { DataHealth, LatestRun } from "./types";

/**
 * FOREX LAB CLIENT
 *
 * Two calls, both read-only. The sweep is run by an operator command —
 * `python -m app.labs.forex_lab sweep` then `publish` — not by loading a page:
 * a backtest result is a thing computed once from a frozen dataset, and a
 * browser that could re-run it with a different step size or a different gate
 * would be a second, unpublished experiment competing with the registered one.
 */
export function fetchLatest(): Promise<LatestRun> {
  return api.get<LatestRun>("/labs/forex-lab/latest");
}

/** What is loaded, so the page can say whether the replay covered the window. */
export function fetchDataHealth(): Promise<DataHealth> {
  return api.get<DataHealth>("/labs/forex-lab/data");
}

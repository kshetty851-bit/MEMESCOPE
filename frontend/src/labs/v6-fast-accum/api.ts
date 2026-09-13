import { api } from "@/lib/api-client";

import type { LatestRun } from "./types";

/**
 * V6 FAST-ACCUMULATION LAB CLIENT
 *
 * One call, and it only reads. The experiment is run by an operator command,
 * not by loading a page: a research result is a thing computed once from a
 * frozen dataset, and a browser that could re-run it with different thresholds
 * would be a second, unpublished experiment competing with the registered one.
 */
export function fetchLatest(): Promise<LatestRun> {
  return api.get<LatestRun>("/labs/v6-fast-accum/latest");
}

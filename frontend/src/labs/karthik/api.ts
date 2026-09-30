import { api } from "@/lib/api-client";

import type { KarthikBook, PumpfunDays } from "./types";

/** One call, read-only. The book decides nothing; the arm behind it trades. */
export function fetchKarthikBook(): Promise<KarthikBook> {
  return api.get<KarthikBook>("/labs/graduation/karthik");
}

/** Pump.fun day by day. Past days are fixed; today refreshes every ten minutes. */
export function fetchPumpfunDays(): Promise<PumpfunDays> {
  return api.get<PumpfunDays>("/labs/graduation/karthik/pumpfun-days");
}

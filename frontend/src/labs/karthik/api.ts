import { api } from "@/lib/api-client";

import type { KarthikBook, PumpfunDays, WalletsProfit } from "./types";

/** One call, read-only. The book decides nothing; the arm behind it trades. */
export function fetchKarthikBook(): Promise<KarthikBook> {
  return api.get<KarthikBook>("/labs/graduation/karthik");
}

/** Pump Catcher Lab (2026-10-24): the same book, sold at +30% or 10 minutes. */
export function fetchPumpCatcherBook(): Promise<KarthikBook> {
  return api.get<KarthikBook>("/labs/graduation/karthik/pump-catcher");
}

/** Pump.fun day by day. Past days are fixed; today refreshes every ten minutes. */
export function fetchPumpfunDays(): Promise<PumpfunDays> {
  return api.get<PumpfunDays>("/labs/graduation/karthik/pumpfun-days");
}

/** The real wallets' profit for the small box: names and figures, no addresses. */
export function fetchWalletsProfit(): Promise<WalletsProfit> {
  return api.get<WalletsProfit>("/real-wallet/wallets-profit");
}

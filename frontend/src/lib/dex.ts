import { api } from "@/lib/api-client";

import type { DexBoard } from "@/types/dex";
import type { LabTrades } from "@/types/lab";

/** The Dex Lab board: the turnover wallet and its control, side by side. */
export function fetchDexBoard(): Promise<DexBoard> {
  return api.get<DexBoard>("/dex/board");
}

/** Every position either arm holds or has closed, each with its own P&L. */
export function fetchDexTrades(strategyId?: string): Promise<LabTrades> {
  const query = new URLSearchParams({ limit: "2000" });
  if (strategyId) query.set("strategy_id", strategyId);
  return api.get<LabTrades>(`/dex/trades?${query.toString()}`);
}

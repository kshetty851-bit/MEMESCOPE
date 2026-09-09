import { api } from "@/lib/api-client";

import type { MoversBoard } from "@/types/movers";
import type { LabTrades } from "@/types/lab";

/** The Movers Lab board: the signal wallet and its control, side by side. */
export function fetchMoversBoard(): Promise<MoversBoard> {
  return api.get<MoversBoard>("/movers/board");
}

/** Every position either arm holds or has closed, each with its own P&L. */
export function fetchMoversTrades(strategyId?: string): Promise<LabTrades> {
  const query = new URLSearchParams({ limit: "2000" });
  if (strategyId) query.set("strategy_id", strategyId);
  return api.get<LabTrades>(`/movers/trades?${query.toString()}`);
}

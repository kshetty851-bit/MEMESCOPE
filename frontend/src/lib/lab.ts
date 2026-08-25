import { api } from "@/lib/api-client";
import type { LabBoard, LabStrategyDetail, LabTrades } from "@/types/lab";

/**
 * Strategy Lab client. Fetches and formats; it never decides and never
 * computes a figure the server owns — the same rule the Arena and wallet
 * clients follow.
 */

export function fetchLabBoard(): Promise<LabBoard> {
  return api.get<LabBoard>("/lab/board");
}

export function fetchLabStrategy(id: string): Promise<LabStrategyDetail> {
  return api.get<LabStrategyDetail>(`/lab/strategies/${id}`);
}

export function fetchLabTrades(
  strategyId?: string,
  status?: "open" | "closed",
): Promise<LabTrades> {
  const query = new URLSearchParams({ limit: "2000" });
  if (strategyId) query.set("strategy_id", strategyId);
  if (status) query.set("status", status);
  return api.get<LabTrades>(`/lab/trades?${query.toString()}`);
}

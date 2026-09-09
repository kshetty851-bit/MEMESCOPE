import { api } from "@/lib/api-client";

import type { MatrixBoard } from "@/types/matrix";
import type { LabTrades } from "@/types/lab";

/** The whole grid: twenty-four arms, ordered by id so the axes stay readable. */
export function fetchMatrixBoard(): Promise<MatrixBoard> {
  return api.get<MatrixBoard>("/matrix/board");
}

/** Positions, filtered to one arm — twenty-four books interleaved is a log,
 *  not a comparison. */
export function fetchMatrixTrades(strategyId?: string): Promise<LabTrades> {
  const query = new URLSearchParams({ limit: "500" });
  if (strategyId) query.set("strategy_id", strategyId);
  return api.get<LabTrades>(`/matrix/trades?${query.toString()}`);
}

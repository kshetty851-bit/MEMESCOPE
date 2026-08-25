import { api } from "@/lib/api-client";
import type { LabBoard, LabStrategyDetail } from "@/types/lab";

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

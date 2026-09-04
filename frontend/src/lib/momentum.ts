import { api } from "@/lib/api-client";

import type { MomentumBoard } from "@/types/momentum";

/** Momentum V2, in one request. Fetches and formats; decides nothing. */
export function fetchMomentumBoard(): Promise<MomentumBoard> {
  return api.get<MomentumBoard>("/momentum/board");
}

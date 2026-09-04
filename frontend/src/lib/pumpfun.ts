import { api } from "@/lib/api-client";

import type { PumpfunBoard } from "@/types/pumpfun";

/** The copy lab, in one request. Fetches and formats; decides nothing. */
export function fetchPumpfunBoard(): Promise<PumpfunBoard> {
  return api.get<PumpfunBoard>("/pumpfun/board");
}

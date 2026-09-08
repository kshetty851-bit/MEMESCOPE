import { api } from "@/lib/api-client";

import type { FiveMinBoard } from "@/types/fivemin";
import type { LabTrades } from "@/types/lab";

/** The Five-Minute Lab's board. Cycles, equity and the open book are computed
 *  server-side by the same service the Compound Lab uses, so this page cannot
 *  disagree with that one about the same arithmetic. */
export function fetchFiveMinBoard(): Promise<FiveMinBoard> {
  return api.get<FiveMinBoard>("/fivemin/board");
}

/** Every position this lab holds or has closed, each with its own P&L and its
 *  full mint. Same shape as `/lab/trades`, scoped to this tournament. */
export function fetchFiveMinTrades(): Promise<LabTrades> {
  return api.get<LabTrades>("/fivemin/trades?limit=2000");
}

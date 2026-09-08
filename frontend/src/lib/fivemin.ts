import { api } from "@/lib/api-client";

import type { FiveMinBoard } from "@/types/fivemin";

/** The Five-Minute Lab's board. Cycles, equity and the open book are computed
 *  server-side by the same service the Compound Lab uses, so this page cannot
 *  disagree with that one about the same arithmetic. */
export function fetchFiveMinBoard(): Promise<FiveMinBoard> {
  return api.get<FiveMinBoard>("/fivemin/board");
}

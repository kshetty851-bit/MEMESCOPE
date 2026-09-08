import { api } from "@/lib/api-client";

import type { CopyComparison } from "@/types/copytrade";

/** The copy-trade comparison. Fetches and formats; decides nothing — the
 *  verdict is computed server-side so one implementation owns it. */
export function fetchCopyComparison(): Promise<CopyComparison> {
  return api.get<CopyComparison>("/copycontrol/comparison");
}

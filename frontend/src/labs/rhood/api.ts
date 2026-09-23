import { api } from "@/lib/api-client";

import type { RhoodStatus } from "./types";

/** One call, read-only. The recorder decides nothing and neither does this. */
export function fetchRhoodStatus(): Promise<RhoodStatus> {
  return api.get<RhoodStatus>("/labs/rhood/status");
}

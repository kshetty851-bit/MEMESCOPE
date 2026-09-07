import { api } from "@/lib/api-client";

import type { DepthBoard } from "@/types/depth";

/** The depth curve, in one request. Fetches and formats; decides nothing. */
export function fetchDepthBoard(): Promise<DepthBoard> {
  return api.get<DepthBoard>("/depth/board");
}

import { api } from "@/lib/api-client";

import type { CompoundBoard } from "@/types/compound";

/** The Compound Lab, in one request. Fetches and formats; decides nothing. */
export function fetchCompoundBoard(): Promise<CompoundBoard> {
  return api.get<CompoundBoard>("/compound/board");
}

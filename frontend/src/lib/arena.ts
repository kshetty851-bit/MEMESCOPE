import { api } from "@/lib/api-client";
import type { ArenaBoard, ArenaDecision } from "@/types/arena";

/**
 * Arena client. Fetches and formats; it never decides and never computes a
 * figure the server owns — the same rule the wallet clients follow, and for
 * the same reason: a number recomputed here would be a second, unpublished
 * answer competing with the one the experiment actually recorded.
 */

export function fetchArenaBoard(): Promise<ArenaBoard> {
  return api.get<ArenaBoard>("/arena");
}

export function fetchArenaDecisions(code?: string, limit = 50): Promise<ArenaDecision[]> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (code) query.set("code", code);
  return api.get<ArenaDecision[]>(`/arena/decisions?${query.toString()}`);
}

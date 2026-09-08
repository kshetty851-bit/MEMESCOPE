import { api } from "@/lib/api-client";

import type { SocialBoard } from "@/types/social";

/** The Social pair, in one request. Fetches and formats; decides nothing. */
export function fetchSocialBoard(): Promise<SocialBoard> {
  return api.get<SocialBoard>("/social/board");
}

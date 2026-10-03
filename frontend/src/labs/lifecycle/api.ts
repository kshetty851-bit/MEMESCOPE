import { api } from "@/lib/api-client";

import type {
  LifecycleHealth,
  LifecycleOverview,
  MemeDetail,
  MemeList,
} from "./types";

/**
 * LIFECYCLE LAB CLIENT
 *
 * Fetches and nothing else. The lab never trades and this client has no write:
 * the admin POST routes (create meme, manual link) are curation tools and are
 * deliberately not reachable from the research UI.
 */
const BASE = "/lifecycle-lab";

export function fetchOverview(): Promise<LifecycleOverview> {
  return api.get<LifecycleOverview>(`${BASE}/overview`);
}

export function fetchHealth(): Promise<LifecycleHealth> {
  return api.get<LifecycleHealth>(`${BASE}/health`);
}

export function fetchMemes(): Promise<MemeList> {
  return api.get<MemeList>(`${BASE}/memes`);
}

export function fetchMeme(slug: string): Promise<MemeDetail> {
  return api.get<MemeDetail>(`${BASE}/memes/${encodeURIComponent(slug)}`);
}

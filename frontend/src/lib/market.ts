import { api } from "@/lib/api-client";
import type { TrendingPage } from "@/types/api";

/**
 * MARKET API CLIENT.
 *
 * `/market/trending` ranks tokens by a column of their most recent market
 * snapshot. That is the whole definition, and it is the backend's.
 *
 * Worth stating because "trending" invites invention: this endpoint does not
 * compute momentum, acceleration, social attention or a composite. It sorts by
 * one measured field. So the screen built on it says *what it is sorted by*
 * rather than claiming tokens are "hot" — a client-side formula dressed up as a
 * trend would be exactly the unversioned second opinion this codebase refuses
 * to hold.
 */

/** The columns `/market/trending` can rank by. Mirrors `TrendingSort`. */
export const TRENDING_SORTS = [
  "volume_24h",
  "volume_1h",
  "volume_5m",
  "liquidity_usd",
  "market_cap",
  "price_usd",
  "captured_at",
] as const;

export type TrendingSort = (typeof TRENDING_SORTS)[number];

/** What each ranking actually means, in the user's words. */
export const TRENDING_SORT_LABEL: Record<TrendingSort, string> = {
  volume_24h: "Volume 24h",
  volume_1h: "Volume 1h",
  volume_5m: "Volume 5m",
  liquidity_usd: "Liquidity",
  market_cap: "Market cap",
  price_usd: "Price",
  captured_at: "Recently observed",
};

export function isTrendingSort(value: string): value is TrendingSort {
  return (TRENDING_SORTS as readonly string[]).includes(value);
}

export function fetchTrending(params: {
  page?: number;
  pageSize?: number;
  sortBy?: TrendingSort;
  minLiquidity?: number | null;
}): Promise<TrendingPage> {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
    sort_by: params.sortBy ?? "volume_24h",
  });
  if (params.minLiquidity && params.minLiquidity > 0) {
    query.set("min_liquidity", String(params.minLiquidity));
  }
  return api.get<TrendingPage>(`/market/trending?${query.toString()}`);
}

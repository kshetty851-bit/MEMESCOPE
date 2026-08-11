"use client";

import { useQuery } from "@tanstack/react-query";

import { useLiveUpdates } from "@/hooks/use-live-updates";
import { fetchTrending, type TrendingSort } from "@/lib/market";
import { livePoll } from "@/lib/query";

/**
 * Trending queries.
 *
 * Polled on the market's cadence rather than the Radar's — this reads the
 * newest snapshot per token, and snapshots land far more often than the
 * fifteen-minute Radar sweep.
 */

const TRENDING_POLL_MS = 45_000;

export function useTrending(params: {
  sortBy: TrendingSort;
  minLiquidity: number;
  pageSize?: number;
}) {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["market", "trending", params],
    queryFn: () =>
      fetchTrending({
        sortBy: params.sortBy,
        minLiquidity: params.minLiquidity,
        pageSize: params.pageSize ?? 50,
      }),
    refetchInterval: livePoll(status, TRENDING_POLL_MS),
    staleTime: TRENDING_POLL_MS / 2,
  });
}

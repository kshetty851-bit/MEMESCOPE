"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useLiveUpdates } from "@/hooks/use-live-updates";

import { api } from "@/lib/api-client";
import type { MarketSnapshot, TrendingPage } from "@/types/api";

/**
 * Market data for the live feed, keyed by mint.
 *
 * The discovery WebSocket carries no market data — enrichment happens in a
 * separate worker on its own schedule. So the feed polls trending sorted by
 * `captured_at`, which surfaces the most recently *refreshed* tokens; since
 * fresh tokens refresh every 30s, that is precisely the set the feed shows.
 *
 * Ranking by volume instead would bury brand-new low-volume launches, which
 * are the ones the feed exists to display.
 */
export function useMarketByMint(pollMs = 15_000) {
  const { status } = useLiveUpdates();
  const { data, isPending } = useQuery({
    queryKey: ["market", "recent"],
    queryFn: () =>
      api.get<TrendingPage>("/market/trending?sort_by=captured_at&page_size=100"),
    refetchInterval: status === "live" ? false : pollMs,
    staleTime: pollMs / 2,
  });

  const byMint = useMemo(() => {
    const map = new Map<string, MarketSnapshot>();
    for (const entry of data?.items ?? []) {
      map.set(entry.token.mint_address, entry.market);
    }
    return map;
  }, [data]);

  return { byMint, isPending };
}

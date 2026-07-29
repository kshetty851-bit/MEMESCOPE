"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { IdentityPage, TokenIdentity } from "@/types/identity";

/**
 * Clone risk for a set of tokens.
 *
 * Batched into one request for the whole page. The home page renders several
 * sections of several tokens each, and a per-card lookup would turn one screen
 * into dozens of round trips — the same duplication `useScoresByMint` was
 * built to avoid.
 *
 * A name collision only changes when a *new* token launches with the same name,
 * which is slow relative to price. So this is cached far longer than market
 * data: refetching it on the scanner's cadence would be pure waste.
 */
const STALE_MS = 10 * 60 * 1000;

export function useIdentities(mints: string[]) {
  // Sorted so two components requesting the same set in different orders share
  // one cache entry rather than fetching twice.
  const key = [...new Set(mints)].sort();

  return useQuery({
    queryKey: ["identity", key],
    enabled: key.length > 0,
    staleTime: STALE_MS,
    queryFn: async () => {
      const page = await api.post<IdentityPage>("/identity/batch", {
        mint_addresses: key,
      });
      return new Map(page.items.map((item) => [item.mint_address, item]));
    },
  });
}

export function useIdentity(mint: string | undefined) {
  return useQuery({
    queryKey: ["identity", "one", mint],
    enabled: Boolean(mint),
    staleTime: STALE_MS,
    queryFn: () => api.get<TokenIdentity>(`/identity/${mint}`),
  });
}

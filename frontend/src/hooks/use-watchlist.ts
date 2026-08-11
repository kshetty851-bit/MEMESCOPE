"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useLiveUpdates } from "@/hooks/use-live-updates";
import { livePoll } from "@/lib/query";
import {
  addWatchlistToken,
  createWatchlist,
  deleteWatchlist,
  fetchWatchlistTokens,
  fetchWatchlists,
  isAlreadyWatched,
  removeWatchlistToken,
} from "@/lib/watchlist";
import type { Watchlist, WatchlistItem } from "@/types/watchlist";

/**
 * Watchlist queries and mutations.
 *
 * Polled slowly. A watchlist changes when the user changes it — the only thing
 * that moves on its own is `current_score` and `last_change`, which track the
 * scoring engine's cadence rather than the market's.
 *
 * Every mutation invalidates rather than hand-patching the cache. The item
 * response carries backend-derived state (`added_*` snapshots, `last_change`)
 * that the client cannot reconstruct, so writing an optimistic row would mean
 * inventing those fields — which is the one thing this codebase does not do.
 */

const WATCHLIST_POLL_MS = 60_000;

export const watchlistKeys = {
  all: ["watchlists"] as const,
  lists: () => ["watchlists", "list"] as const,
  tokens: (listId: string) => ["watchlists", listId, "tokens"] as const,
};

export function useWatchlists() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: watchlistKeys.lists(),
    queryFn: fetchWatchlists,
    refetchInterval: livePoll(status, WATCHLIST_POLL_MS),
    staleTime: WATCHLIST_POLL_MS / 2,
  });
}

export function useWatchlistTokens(listId: string | undefined) {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: watchlistKeys.tokens(listId ?? "none"),
    queryFn: () => fetchWatchlistTokens(listId!),
    enabled: Boolean(listId),
    refetchInterval: livePoll(status, WATCHLIST_POLL_MS),
    staleTime: WATCHLIST_POLL_MS / 2,
  });
}

export function useCreateWatchlist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createWatchlist,
    onSuccess: (created: Watchlist) => {
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.all });
      return created;
    },
  });
}

export function useDeleteWatchlist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteWatchlist,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.all });
    },
  });
}

export function useAddToWatchlist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      listId,
      mint,
      note,
    }: {
      listId: string;
      mint: string;
      note?: string | null;
    }): Promise<WatchlistItem | null> => {
      try {
        return await addWatchlistToken(listId, { mint_address: mint, note });
      } catch (error) {
        // Already on the list is the outcome the caller wanted. Surfacing it as
        // a failure would make a double-click look broken.
        if (isAlreadyWatched(error)) return null;
        throw error;
      }
    },
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.tokens(variables.listId) });
      // The list's `item_count` lives on the collection response.
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.lists() });
    },
  });
}

export function useRemoveFromWatchlist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ listId, mint }: { listId: string; mint: string }) =>
      removeWatchlistToken(listId, mint),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.tokens(variables.listId) });
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.lists() });
    },
  });
}

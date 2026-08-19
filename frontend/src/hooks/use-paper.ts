"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLiveUpdates } from "@/hooks/use-live-updates";
import { livePoll } from "@/lib/query";

import {
  fetchPaperAudit,
  fetchPaperPerformance,
  fetchPaperPositions,
  fetchPaperStrategies,
  fetchPaperWallet,
  fetchPaperWalletContext,
  previewManualSell,
  sellPaperPosition,
} from "@/lib/paper";

/**
 * Paper wallet queries.
 *
 * Polled on the simulation's cadence, not the market's. The review beat runs
 * every five minutes, so refetching every twenty seconds would issue fifteen
 * requests to observe one change.
 *
 * The published strategy is static for the lifetime of a deploy — its rules are
 * code — so it is fetched once and never refetched.
 */

const PAPER_POLL_MS = 120_000;

export function usePaperWallet() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["paper", "wallet"],
    queryFn: fetchPaperWallet,
    refetchInterval: livePoll(status, PAPER_POLL_MS),
    staleTime: PAPER_POLL_MS / 2,
  });
}

export function usePaperWalletContext(roiPct?: string | null) {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["paper", "wallet-context", roiPct],
    queryFn: () => fetchPaperWalletContext(roiPct),
    refetchInterval: livePoll(status, PAPER_POLL_MS),
    staleTime: PAPER_POLL_MS / 2,
  });
}

export function usePaperPositions() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["paper", "positions"],
    queryFn: fetchPaperPositions,
    refetchInterval: livePoll(status, PAPER_POLL_MS),
    staleTime: PAPER_POLL_MS / 2,
  });
}

/**
 * The permanent trade record.
 *
 * Polled on the same cadence as the wallet. It only grows when a position
 * closes, and a row in it never changes — nothing in the backend updates the
 * audit table — so a cached page can never be showing a stale version of a
 * trade, only a shorter list.
 */
export function usePaperAudit(limit = 100) {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["paper", "audit", limit],
    queryFn: () => fetchPaperAudit(limit),
    refetchInterval: livePoll(status, PAPER_POLL_MS),
    staleTime: PAPER_POLL_MS / 2,
  });
}

/** The date-by-date returns category, sourced from the immutable trade log. */
export function usePaperPerformance() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["paper", "performance"],
    queryFn: fetchPaperPerformance,
    refetchInterval: livePoll(status, PAPER_POLL_MS),
    staleTime: PAPER_POLL_MS / 2,
  });
}

export function usePaperStrategies() {
  return useQuery({
    queryKey: ["paper", "strategies"],
    queryFn: fetchPaperStrategies,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function useManualSellPreview() {
  return useMutation({
    mutationFn: previewManualSell,
  });
}

export function useManualSell() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: sellPaperPosition,
    onSuccess: () => {
      for (const key of [
        ["paper", "wallet"],
        ["paper", "positions"],
        ["paper", "audit"],
        ["paper", "performance"],
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}

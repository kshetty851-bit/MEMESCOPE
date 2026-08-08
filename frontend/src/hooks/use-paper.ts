"use client";

import { useQuery } from "@tanstack/react-query";
import { useLiveUpdates } from "@/hooks/use-live-updates";

import {
  fetchLab,
  fetchLabTokens,
  fetchPaperAudit,
  fetchPaperPositions,
  fetchPaperStrategies,
  fetchPaperWallet,
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
    refetchInterval: status === "live" ? false : PAPER_POLL_MS,
    staleTime: PAPER_POLL_MS / 2,
  });
}

export function usePaperPositions() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["paper", "positions"],
    queryFn: fetchPaperPositions,
    refetchInterval: status === "live" ? false : PAPER_POLL_MS,
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
    refetchInterval: status === "live" ? false : PAPER_POLL_MS,
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

/**
 * The Strategy Lab.
 *
 * Replayed server-side over stored history, so the answer only changes when new
 * snapshots land. Polled on the same cadence as the wallet rather than more
 * often — the replay is deterministic, and refetching it faster would issue
 * requests to observe a figure that did not move.
 */
export function useLab() {
  return useQuery({
    queryKey: ["paper", "lab"],
    queryFn: fetchLab,
    // Lab has no committed invalidation event: it is a broad historical replay,
    // not a live wallet read model. Keep its deliberately slow poll.
    refetchInterval: PAPER_POLL_MS,
    staleTime: PAPER_POLL_MS / 2,
  });
}

export function useLabTokens(limit = 60) {
  return useQuery({
    queryKey: ["paper", "lab", "tokens", limit],
    queryFn: () => fetchLabTokens(limit),
    staleTime: PAPER_POLL_MS,
  });
}

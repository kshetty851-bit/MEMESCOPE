"use client";

import { useQuery } from "@tanstack/react-query";

import {
  fetchLab,
  fetchLabTokens,
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
  return useQuery({
    queryKey: ["paper", "wallet"],
    queryFn: fetchPaperWallet,
    refetchInterval: PAPER_POLL_MS,
    staleTime: PAPER_POLL_MS / 2,
  });
}

export function usePaperPositions() {
  return useQuery({
    queryKey: ["paper", "positions"],
    queryFn: fetchPaperPositions,
    refetchInterval: PAPER_POLL_MS,
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

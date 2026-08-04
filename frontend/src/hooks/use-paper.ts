"use client";

import { useQuery } from "@tanstack/react-query";

import {
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

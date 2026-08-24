"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchArenaBoard, fetchArenaDecisions } from "@/lib/arena";

/**
 * Arena queries. Polled on the beat's cadence (one minute), not the market's:
 * the Arena judges once a minute, so a faster refetch would issue requests to
 * observe a number that cannot have changed.
 */
const ARENA_POLL_MS = 60_000;

export function useArenaBoard() {
  return useQuery({
    queryKey: ["arena", "board"],
    queryFn: fetchArenaBoard,
    refetchInterval: ARENA_POLL_MS,
  });
}

export function useArenaDecisions(code?: string) {
  return useQuery({
    queryKey: ["arena", "decisions", code ?? "all"],
    queryFn: () => fetchArenaDecisions(code),
    refetchInterval: ARENA_POLL_MS,
  });
}

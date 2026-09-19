"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchBoard, fetchSignals, fetchStatus, fetchTrades } from "./api";

/**
 * Nothing pushes this page: every figure is polled, and the book trades on a
 * thirty-second tick whether or not anyone is looking. So refetch on focus
 * and never serve a cached figure to a returning reader (the graduation page
 * froze at 211 closed trades while the database held 612 without this).
 */
const LIVE = { refetchOnWindowFocus: true, staleTime: 0 } as const;

export function useMomentumStatus() {
  return useQuery({
    queryKey: ["momentum", "status"],
    queryFn: fetchStatus,
    refetchInterval: 30_000,
    ...LIVE,
  });
}

export function useMomentumBoard() {
  return useQuery({
    queryKey: ["momentum", "board"],
    queryFn: fetchBoard,
    refetchInterval: 30_000,
    ...LIVE,
  });
}

export function useMomentumTrades(arm: string | null) {
  return useQuery({
    queryKey: ["momentum", "trades", arm],
    queryFn: () => fetchTrades(arm ?? ""),
    enabled: arm !== null,
    refetchInterval: 60_000,
    ...LIVE,
  });
}

export function useMomentumSignals() {
  return useQuery({
    queryKey: ["momentum", "signals"],
    queryFn: fetchSignals,
    refetchInterval: 30_000,
    ...LIVE,
  });
}

"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchLabBoard, fetchLabStrategy, fetchLabTrades } from "@/lib/lab";

/**
 * Lab queries. Polled on the beat's cadence (one minute), not the market's:
 * the Lab judges once a minute, so a faster refetch would issue requests to
 * observe a number that cannot have changed.
 */
const LAB_POLL_MS = 60_000;

export function useLabBoard() {
  return useQuery({
    queryKey: ["lab", "board"],
    queryFn: fetchLabBoard,
    refetchInterval: LAB_POLL_MS,
  });
}

export function useLabStrategy(id: string | null) {
  return useQuery({
    queryKey: ["lab", "strategy", id],
    queryFn: () => fetchLabStrategy(id as string),
    enabled: Boolean(id),
    refetchInterval: LAB_POLL_MS,
  });
}

export function useLabTrades(strategyId?: string, status?: "open" | "closed") {
  return useQuery({
    queryKey: ["lab", "trades", strategyId ?? "all", status ?? "all"],
    queryFn: () => fetchLabTrades(strategyId, status),
    refetchInterval: LAB_POLL_MS,
  });
}

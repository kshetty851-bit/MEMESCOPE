"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchMoversBoard, fetchMoversTrades } from "@/lib/movers";

export function useMoversBoard() {
  return useQuery({
    queryKey: ["movers", "board"],
    queryFn: fetchMoversBoard,
    // The hold is thirty minutes and the beat runs every minute, so a page
    // older than a minute can be a whole position behind.
    refetchInterval: 30_000,
  });
}

export function useMoversTrades(strategyId?: string) {
  return useQuery({
    queryKey: ["movers", "trades", strategyId ?? "all"],
    queryFn: () => fetchMoversTrades(strategyId),
    refetchInterval: 30_000,
  });
}

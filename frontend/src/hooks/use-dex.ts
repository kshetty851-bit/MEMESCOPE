"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchDexBoard, fetchDexTrades } from "@/lib/dex";

export function useDexBoard() {
  return useQuery({
    queryKey: ["dex", "board"],
    queryFn: fetchDexBoard,
    // The hold is six hours, so a page a minute stale is never a position
    // behind. Thirty seconds matches the other lab pages rather than tuning
    // one of them differently for no reason a reader could see.
    refetchInterval: 30_000,
  });
}

export function useDexTrades(strategyId?: string) {
  return useQuery({
    queryKey: ["dex", "trades", strategyId ?? "all"],
    queryFn: () => fetchDexTrades(strategyId),
    refetchInterval: 30_000,
  });
}

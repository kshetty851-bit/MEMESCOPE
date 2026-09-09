"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchMatrixBoard, fetchMatrixTrades } from "@/lib/matrix";

export function useMatrixBoard() {
  return useQuery({
    queryKey: ["matrix", "board"],
    queryFn: fetchMatrixBoard,
    // The shortest clock is five minutes and the beat runs every minute.
    refetchInterval: 30_000,
  });
}

export function useMatrixTrades(strategyId?: string) {
  return useQuery({
    queryKey: ["matrix", "trades", strategyId ?? "all"],
    queryFn: () => fetchMatrixTrades(strategyId),
    refetchInterval: 30_000,
  });
}

"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchKarthikBook, fetchPumpfunDays, fetchWalletsProfit } from "./api";

/** The book closes a trade every few minutes, so the page follows at a minute. */
export function useKarthikBook() {
  return useQuery({
    queryKey: ["karthik-lab", "book"],
    queryFn: fetchKarthikBook,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function usePumpfunDays() {
  return useQuery({
    queryKey: ["karthik-lab", "pumpfun-days"],
    queryFn: fetchPumpfunDays,
    refetchInterval: 600_000,
    staleTime: 300_000,
  });
}

/** Real money, so it follows closer than the paper book: every 30 seconds. */
export function useWalletsProfit() {
  return useQuery({
    queryKey: ["karthik-lab", "wallets-profit"],
    queryFn: fetchWalletsProfit,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

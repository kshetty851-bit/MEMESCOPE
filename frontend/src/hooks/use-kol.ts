"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchKolBoard, fetchKolTrades, fetchKolWallets } from "@/lib/kol";

export function useKolBoard() {
  return useQuery({
    queryKey: ["kol", "board"],
    queryFn: fetchKolBoard,
    refetchInterval: 30_000,
  });
}

export function useKolWallets() {
  return useQuery({
    queryKey: ["kol", "wallets"],
    queryFn: fetchKolWallets,
    // The ranking is frozen once and then never changes, but until it exists
    // this is the page's only progress indicator.
    refetchInterval: 60_000,
  });
}

export function useKolTrades() {
  return useQuery({
    queryKey: ["kol", "trades"],
    queryFn: fetchKolTrades,
    refetchInterval: 30_000,
  });
}

"use client";

import { useQuery } from "@tanstack/react-query";

import { useLiveUpdates } from "@/hooks/use-live-updates";
import {
  fetchKarthikPositions,
  fetchKarthikSkipped,
  fetchKarthikWallet,
} from "@/lib/karthik";
import { livePoll } from "@/lib/query";

/**
 * Karthik wallet queries.
 *
 * Polled on the review's cadence, not the market's. Karthik reviews once a
 * minute, so a twenty-second refetch would issue three requests to observe one
 * change. Its own query keys, so nothing here shares a cache entry with the
 * Original Paper Wallet — two wallets whose caches could collide is one wallet
 * showing the other's numbers.
 */

const KARTHIK_POLL_MS = 60_000;

export function useKarthikWallet() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["karthik", "wallet"],
    queryFn: fetchKarthikWallet,
    refetchInterval: livePoll(status, KARTHIK_POLL_MS),
    staleTime: KARTHIK_POLL_MS / 2,
  });
}

export function useKarthikPositions() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["karthik", "positions"],
    queryFn: fetchKarthikPositions,
    refetchInterval: livePoll(status, KARTHIK_POLL_MS),
    staleTime: KARTHIK_POLL_MS / 2,
  });
}

export function useKarthikSkipped() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["karthik", "skipped"],
    queryFn: fetchKarthikSkipped,
    refetchInterval: livePoll(status, KARTHIK_POLL_MS),
    staleTime: KARTHIK_POLL_MS / 2,
  });
}

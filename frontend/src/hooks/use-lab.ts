"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchCompoundBoard } from "@/lib/compound";
import { fetchMomentumBoard } from "@/lib/momentum";
import { fetchPumpfunBoard } from "@/lib/pumpfun";
import {
  closeLabPosition,
  fetchLabBoard,
  fetchLabSnapshots,
  fetchLabStrategy,
  fetchLabTrades,
} from "@/lib/lab";

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

/** Frozen boards. They never change once written, so this polls slowly. */
export function useLabSnapshots() {
  return useQuery({
    queryKey: ["lab", "snapshots"],
    queryFn: fetchLabSnapshots,
    refetchInterval: 5 * LAB_POLL_MS,
  });
}

/**
 * Close one position by hand.
 *
 * Invalidates every Lab query rather than just the strategy's own: the close
 * returns cash, which moves that wallet's equity and therefore its rank, so a
 * board left un-refetched would disagree with the panel the click happened in
 * until the next poll.
 */
export function useCloseLabPosition() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: closeLabPosition,
    onSettled: () => client.invalidateQueries({ queryKey: ["lab"] }),
  });
}

/** The Compound Lab. Same cadence as the Lab it shares an engine with. */
export function useCompoundBoard() {
  return useQuery({
    queryKey: ["compound", "board"],
    queryFn: fetchCompoundBoard,
    refetchInterval: LAB_POLL_MS,
  });
}

/** The PumpFun copy lab. Polls on the beat's cadence, like the other labs. */
export function usePumpfunBoard() {
  return useQuery({
    queryKey: ["pumpfun", "board"],
    queryFn: fetchPumpfunBoard,
    refetchInterval: LAB_POLL_MS,
  });
}

/** Momentum V2. Same cadence as the tournaments it shares an engine with. */
export function useMomentumBoard() {
  return useQuery({
    queryKey: ["momentum", "board"],
    queryFn: fetchMomentumBoard,
    refetchInterval: LAB_POLL_MS,
  });
}

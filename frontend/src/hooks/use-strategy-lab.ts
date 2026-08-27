"use client";

import { useQuery } from "@tanstack/react-query";

import {
  fetchLabCompare,
  fetchLabExperiments,
  fetchLabLeaderboard,
  fetchLabOverview,
  fetchLabRugs,
  fetchLabStatus,
  fetchLabStrategies,
  fetchLabStrategyDetail,
  type LabMode,
  type LabWindow,
} from "@/lib/strategy-lab";

/**
 * Strategy Lab queries.
 *
 * Polled on the research cadence, not the market's. The forward tick runs every
 * five minutes, so refetching every twenty seconds would issue fifteen requests
 * to observe one change. The historical replay changes only when someone runs
 * it, which is rarer still.
 *
 * The strategy *definitions* are code and are static for the lifetime of a
 * deploy, so they are fetched once and never refetched.
 */

const LAB_POLL_MS = 120_000;

export function useLabOverview(mode: LabMode) {
  return useQuery({
    queryKey: ["strategy-lab", "overview", mode],
    queryFn: () => fetchLabOverview(mode),
    refetchInterval: LAB_POLL_MS,
    staleTime: LAB_POLL_MS / 2,
  });
}

export function useLabLeaderboard(mode: LabMode, window: LabWindow) {
  return useQuery({
    queryKey: ["strategy-lab", "leaderboard", mode, window],
    queryFn: () => fetchLabLeaderboard(mode, window),
    refetchInterval: LAB_POLL_MS,
    staleTime: LAB_POLL_MS / 2,
  });
}

export function useLabStrategies() {
  return useQuery({
    queryKey: ["strategy-lab", "strategies"],
    queryFn: fetchLabStrategies,
    staleTime: Infinity,
  });
}

export function useLabStrategyDetail(strategyId: string | null, mode: LabMode) {
  return useQuery({
    queryKey: ["strategy-lab", "strategy", strategyId, mode],
    queryFn: () => fetchLabStrategyDetail(strategyId as string, mode),
    enabled: Boolean(strategyId),
    refetchInterval: LAB_POLL_MS,
  });
}

export function useLabCompare(mint: string | null, mode: LabMode) {
  return useQuery({
    queryKey: ["strategy-lab", "compare", mint, mode],
    queryFn: () => fetchLabCompare(mint as string, mode),
    enabled: Boolean(mint && mint.length >= 32),
    retry: false,
  });
}

export function useLabRugs(mode: LabMode) {
  return useQuery({
    queryKey: ["strategy-lab", "rugs", mode],
    queryFn: () => fetchLabRugs(mode),
    refetchInterval: LAB_POLL_MS,
  });
}

export function useLabExperiments(mode: LabMode) {
  return useQuery({
    queryKey: ["strategy-lab", "experiments", mode],
    queryFn: () => fetchLabExperiments(mode),
    refetchInterval: LAB_POLL_MS,
  });
}

export function useLabStatus() {
  return useQuery({
    queryKey: ["strategy-lab", "status"],
    queryFn: fetchLabStatus,
    refetchInterval: LAB_POLL_MS,
  });
}

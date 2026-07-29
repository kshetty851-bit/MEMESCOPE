"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import type { ExitWatchPage, HallEntry, Leaderboard } from "@/types/intelligence";

/**
 * Exit Watch and record queries.
 *
 * Exit Watch is assessed live on the backend from stored series, so it is
 * polled on the Radar's cadence rather than the scanner's — the underlying
 * data only moves when enrichment writes a new snapshot.
 */
const POLL_MS = 120_000;

export function useExitWatch(severity?: "watch" | "elevated") {
  return useQuery({
    queryKey: ["intelligence", "exit-watch", severity ?? "all"],
    queryFn: () =>
      api.get<ExitWatchPage>(`/exit-watch${severity ? `?severity=${severity}` : ""}`),
    refetchInterval: POLL_MS,
    staleTime: POLL_MS / 2,
  });
}

export function useHallOfFame(limit = 25) {
  return useQuery({
    queryKey: ["intelligence", "hall-of-fame", limit],
    queryFn: () => api.get<HallEntry[]>(`/hall-of-fame?limit=${limit}`),
    staleTime: POLL_MS,
  });
}

export function useHallOfLessons(limit = 25) {
  return useQuery({
    queryKey: ["intelligence", "hall-of-lessons", limit],
    queryFn: () => api.get<HallEntry[]>(`/hall-of-lessons?limit=${limit}`),
    staleTime: POLL_MS,
  });
}

export function useLeaderboard(limit = 10) {
  return useQuery({
    queryKey: ["intelligence", "leaderboard", limit],
    queryFn: () => api.get<Leaderboard>(`/leaderboard?limit=${limit}`),
    staleTime: POLL_MS,
  });
}

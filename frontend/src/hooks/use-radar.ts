"use client";

import { useQuery } from "@tanstack/react-query";
import { useLiveUpdates } from "@/hooks/use-live-updates";

import {
  fetchRadar,
  fetchAllRadarDetections,
  fetchFreshDetectedTokens,
  fetchRadarEntry,
  fetchRadarHistory,
  fetchRadarModel,
  fetchRadarBenchmark,
  fetchRadarPerformance,
  fetchRadarTimeline,
} from "@/lib/radar";
import type { RadarCategory } from "@/types/radar";

/**
 * Radar queries.
 *
 * Polled far more slowly than the live feed. The Radar sweeps every fifteen
 * minutes on the backend, so refetching every twenty seconds would issue forty
 * requests to observe one change — the cadence matches the data's, not the
 * scanner's.
 */

const RADAR_POLL_MS = 120_000;

export function useRadar(params: {
  category?: RadarCategory | null;
  sort?: "score" | "detected" | "peak" | "current";
  includeInactive?: boolean;
  page?: number;
  pageSize?: number;
}) {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["radar", "list", params],
    queryFn: () => fetchRadar(params),
    refetchInterval: status === "live" ? false : RADAR_POLL_MS,
    staleTime: RADAR_POLL_MS / 2,
  });
}

export function useAllRadarDetections(params: {
  category?: RadarCategory | null;
  sort?: "score" | "detected" | "peak" | "current";
  includeInactive?: boolean;
}) {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["radar", "all-detections", params],
    queryFn: () => fetchAllRadarDetections(params),
    refetchInterval: status === "live" ? false : RADAR_POLL_MS,
    staleTime: RADAR_POLL_MS / 2,
  });
}

export function useRadarEntry(mint: string | undefined) {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["radar", "entry", mint],
    queryFn: () => fetchRadarEntry(mint!),
    enabled: Boolean(mint),
    refetchInterval: status === "live" ? false : RADAR_POLL_MS,
  });
}

export function useFreshDetectedTokens(limit = 30) {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["tokens", "fresh", limit],
    queryFn: () => fetchFreshDetectedTokens(limit),
    refetchInterval: status === "live" ? false : 30_000,
    staleTime: 10_000,
  });
}

export function useRadarHistory(mint: string | undefined, limit = 100) {
  return useQuery({
    queryKey: ["radar", "history", mint, limit],
    queryFn: () => fetchRadarHistory(mint!, limit),
    enabled: Boolean(mint),
    staleTime: RADAR_POLL_MS,
  });
}

export function useRadarPerformance() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["radar", "performance"],
    queryFn: fetchRadarPerformance,
    refetchInterval: status === "live" ? false : RADAR_POLL_MS,
    staleTime: RADAR_POLL_MS / 2,
  });
}

/**
 * The published model. Static for the lifetime of a deploy, so fetched once.
 *
 * Publishing it is what lets the UI state honestly that a category is declared
 * but unreachable, rather than silently never showing it.
 */
export function useRadarTimeline(limit = 50) {
  return useQuery({
    queryKey: ["radar", "timeline", limit],
    queryFn: () => fetchRadarTimeline(limit),
    staleTime: 30_000,
  });
}

export function useRadarBenchmark() {
  return useQuery({
    queryKey: ["radar", "benchmark"],
    queryFn: fetchRadarBenchmark,
    staleTime: 30_000,
  });
}

export function useRadarModel() {
  return useQuery({
    queryKey: ["radar", "model"],
    queryFn: fetchRadarModel,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

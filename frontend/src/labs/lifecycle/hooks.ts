"use client";

import { useQuery } from "@tanstack/react-query";

import {
  fetchHealth,
  fetchMeme,
  fetchMemeQuality,
  fetchMemes,
  fetchOverview,
  fetchQuality,
  fetchResearchStatus,
} from "./api";

/**
 * Same cadence and same reasoning as the Graduation Lab's hooks: collection and
 * the forward replay tick continuously, nothing is pushed over the live stream,
 * and the app-wide default of not refetching on focus would hand a returning
 * reader a frozen board. Polling pauses while the tab is hidden, which is
 * right; the answer is fetched the instant the reader is back.
 */
const REFRESH_MS = 30_000;

const LIVE = {
  refetchOnWindowFocus: true,
  staleTime: 0,
} as const;

export function useLifecycleOverview() {
  return useQuery({
    queryKey: ["lifecycle-lab", "overview"],
    queryFn: fetchOverview,
    refetchInterval: REFRESH_MS,
    ...LIVE,
  });
}

export function useLifecycleHealth() {
  return useQuery({
    queryKey: ["lifecycle-lab", "health"],
    queryFn: fetchHealth,
    refetchInterval: REFRESH_MS,
    ...LIVE,
  });
}

export function useLifecycleMemes() {
  return useQuery({
    queryKey: ["lifecycle-lab", "memes"],
    queryFn: fetchMemes,
    refetchInterval: REFRESH_MS,
    ...LIVE,
  });
}

export function useLifecycleMeme(slug: string) {
  return useQuery({
    queryKey: ["lifecycle-lab", "meme", slug],
    queryFn: () => fetchMeme(slug),
    refetchInterval: REFRESH_MS,
    enabled: slug.length > 0,
    ...LIVE,
  });
}

export function useLifecycleQuality() {
  return useQuery({
    queryKey: ["lifecycle-lab", "quality"],
    queryFn: fetchQuality,
    refetchInterval: REFRESH_MS,
    ...LIVE,
  });
}

export function useLifecycleMemeQuality(slug: string) {
  return useQuery({
    queryKey: ["lifecycle-lab", "meme-quality", slug],
    queryFn: () => fetchMemeQuality(slug),
    refetchInterval: REFRESH_MS,
    enabled: slug.length > 0,
    ...LIVE,
  });
}

/** Fallback for an overview that predates `research_status`; off by default. */
export function useResearchStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["lifecycle-lab", "research-status"],
    queryFn: fetchResearchStatus,
    refetchInterval: REFRESH_MS,
    enabled,
    ...LIVE,
  });
}

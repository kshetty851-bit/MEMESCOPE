"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchDataHealth, fetchLatest } from "./api";

/**
 * A published sweep is IMMUTABLE — it never changes after it is written, and
 * the next one only appears when an operator publishes it. So this page does
 * not poll: it fetches once and stays put, the way the V6 lab's does.
 *
 * The data health call is separate and DOES go stale, because the loader can
 * be running while someone reads the page — that is exactly the situation the
 * coverage banner exists to describe.
 */
export function useForexLabLatest() {
  return useQuery({
    queryKey: ["forex-lab", "latest"],
    queryFn: fetchLatest,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function useForexLabData() {
  return useQuery({
    queryKey: ["forex-lab", "data"],
    queryFn: fetchDataHealth,
    staleTime: 60_000,
  });
}

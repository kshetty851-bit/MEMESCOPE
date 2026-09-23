"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchRhoodStatus } from "./api";

/** The recorder writes every minute, so the page follows at the same pace. */
export function useRhoodStatus() {
  return useQuery({
    queryKey: ["rhood", "status"],
    queryFn: fetchRhoodStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

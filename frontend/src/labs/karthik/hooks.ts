"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchKarthikBook } from "./api";

/** The book closes a trade every few minutes, so the page follows at a minute. */
export function useKarthikBook() {
  return useQuery({
    queryKey: ["karthik-lab", "book"],
    queryFn: fetchKarthikBook,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

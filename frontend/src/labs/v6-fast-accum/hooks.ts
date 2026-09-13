"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchLatest } from "./api";

/**
 * A completed research run is IMMUTABLE — it never changes after it is written,
 * and the next one only appears when an operator runs the command. So this page
 * does not poll: it fetches once and stays put.
 *
 * That is the opposite of the Graduation Lab's board, which polls every thirty
 * seconds because its numbers move on their own. Polling here would issue a
 * request a minute to re-read a row that cannot have changed.
 */
export function useV6Latest() {
  return useQuery({
    queryKey: ["v6-fast-accum", "latest"],
    queryFn: fetchLatest,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

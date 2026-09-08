"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchFiveMinBoard } from "@/lib/fivemin";

export function useFiveMinBoard() {
  return useQuery({
    queryKey: ["fivemin", "board"],
    // Faster than the other boards on purpose: the hold under test is five
    // minutes, so a sixty-second page is a twelfth of the whole position life.
    queryFn: fetchFiveMinBoard,
    refetchInterval: 30_000,
  });
}

"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchStatus } from "./api";

/**
 * The recorder polls the chain every fifteen seconds and the launch feed runs
 * continuously, so thirty seconds keeps the board close to live without
 * issuing requests faster than the numbers can move.
 */
const REFRESH_MS = 30_000;

export function useGraduationStatus() {
  return useQuery({
    queryKey: ["graduation", "status"],
    queryFn: fetchStatus,
    refetchInterval: REFRESH_MS,
  });
}

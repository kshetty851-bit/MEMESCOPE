"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { fetchConfig, fetchStatus, runBacktest } from "./api";
import type { BacktestIn } from "./types";

/**
 * Candles close every few minutes at the shortest and the book only moves on
 * a close, so thirty seconds keeps the page close to live without asking
 * faster than the numbers can change.
 */
const REFRESH_MS = 30_000;

/**
 * Why the status query overrides the app-wide defaults — the same reason the
 * graduation lab does (see `labs/graduation/hooks.ts`). Polling pauses while
 * the tab is hidden and the app turns `refetchOnWindowFocus` off for healthy
 * queries on the assumption that a stream pushes changes. Nothing pushes this
 * lab, so a returning reader would see the figures they left. Refetch on focus
 * and never serve a cached answer.
 */
export function useBtcRangeStatus() {
  return useQuery({
    queryKey: ["btc-range", "status"],
    queryFn: fetchStatus,
    refetchInterval: REFRESH_MS,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
}

/**
 * Bounds and defaults change only on a deploy, so one fetch per page load is
 * enough. Not refetched on focus: a form being edited must not have its
 * defaults swapped underneath it.
 */
export function useBtcRangeConfig() {
  return useQuery({
    queryKey: ["btc-range", "config"],
    queryFn: fetchConfig,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

/** A mutation, not a query: a backtest runs when asked and is never polled. */
export function useRunBacktest() {
  return useMutation({
    mutationFn: (body: BacktestIn) => runBacktest(body),
  });
}

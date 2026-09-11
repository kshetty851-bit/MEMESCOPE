"use client";

import { useQuery } from "@tanstack/react-query";

import {
  fetchAccount,
  fetchEpisodes,
  fetchEquity,
  fetchHealth,
  fetchPositions,
  fetchSetupDetail,
  fetchSetups,
  fetchStats,
  fetchTradeStats,
  fetchTrades,
} from "./api";

/**
 * Two cadences, matched to how fast each thing can actually change.
 *
 * The lab evaluates setups and the book once an HOUR, on the close of the
 * hourly bar — so a one-minute refetch would issue sixty requests to observe
 * a number that cannot have moved. A minute is still fast enough that the
 * page is never visibly behind the tick, and the slower set (the record, the
 * statistics, the curve) moves only when a trade closes.
 */
const FAST_MS = 60_000;
const SLOW_MS = 300_000;

export function useHealth() {
  return useQuery({ queryKey: ["breakout", "health"], queryFn: fetchHealth,
    refetchInterval: FAST_MS });
}

export function useSetups(enabled = true) {
  return useQuery({ queryKey: ["breakout", "setups"], queryFn: fetchSetups,
    refetchInterval: FAST_MS, enabled });
}

export function useAccount(enabled = true) {
  return useQuery({ queryKey: ["breakout", "account"], queryFn: fetchAccount,
    refetchInterval: FAST_MS, enabled });
}

export function usePositions(enabled = true) {
  return useQuery({ queryKey: ["breakout", "positions"], queryFn: fetchPositions,
    refetchInterval: FAST_MS, enabled });
}

export function useEpisodes(limit: number, offset: number, enabled = true) {
  return useQuery({ queryKey: ["breakout", "episodes", limit, offset],
    queryFn: () => fetchEpisodes(limit, offset), refetchInterval: SLOW_MS, enabled });
}

export function useTrades(limit: number, offset: number, enabled = true) {
  return useQuery({ queryKey: ["breakout", "trades", limit, offset],
    queryFn: () => fetchTrades(limit, offset), refetchInterval: SLOW_MS, enabled });
}

export function useEquity(hours: number, enabled = true) {
  return useQuery({ queryKey: ["breakout", "equity", hours],
    queryFn: () => fetchEquity(hours), refetchInterval: SLOW_MS, enabled });
}

export function useStats(enabled = true) {
  return useQuery({ queryKey: ["breakout", "stats"], queryFn: fetchStats,
    refetchInterval: SLOW_MS, enabled });
}

export function useTradeStats(enabled = true) {
  return useQuery({ queryKey: ["breakout", "trade-stats"], queryFn: fetchTradeStats,
    refetchInterval: SLOW_MS, enabled });
}

/** The token panel. Only fetched while a mint is selected. */
export function useSetupDetail(mint: string | null) {
  return useQuery({ queryKey: ["breakout", "setup", mint],
    queryFn: () => fetchSetupDetail(mint as string), enabled: Boolean(mint),
    refetchInterval: FAST_MS });
}

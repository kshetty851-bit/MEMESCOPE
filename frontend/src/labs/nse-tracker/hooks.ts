"use client";

import { useQuery } from "@tanstack/react-query";

import {
  fetchBreakouts,
  fetchEpisodes,
  fetchHealth,
  fetchNear,
  fetchStats,
  fetchStock,
} from "./api";
import type { Source } from "./types";

/**
 * One cadence, matched to how fast the data can actually change.
 *
 * **The exchange publishes one bar a day.** Every number on this page is
 * computed from the daily close, so a one-minute refetch would issue hundreds
 * of requests to observe a figure that cannot move until tomorrow evening.
 * Five minutes is already generous; it exists so a page left open across the
 * 18:30 IST ingest picks up the new day without a reload.
 *
 * The replay statistics are slower still — they only change when the replay is
 * re-run, which is a deliberate act.
 */
const DAILY_MS = 300_000;
const STATIC_MS = 900_000;

export function useHealth() {
  return useQuery({ queryKey: ["nse-tracker", "health"], queryFn: fetchHealth,
    refetchInterval: DAILY_MS });
}

export function useNear(enabled = true) {
  return useQuery({ queryKey: ["nse-tracker", "near"], queryFn: () => fetchNear(),
    refetchInterval: DAILY_MS, enabled });
}

export function useBreakouts(days: number, source: Source = "live",
                             enabled = true) {
  return useQuery({ queryKey: ["nse-tracker", "breakouts", days, source],
    queryFn: () => fetchBreakouts(days, source), refetchInterval: DAILY_MS,
    enabled });
}

export function useEpisodes(source: Source, limit: number, offset: number,
                            enabled = true) {
  return useQuery({ queryKey: ["nse-tracker", "episodes", source, limit, offset],
    queryFn: () => fetchEpisodes(source, limit, offset),
    refetchInterval: STATIC_MS, enabled });
}

export function useStats(source: Source, enabled = true) {
  return useQuery({ queryKey: ["nse-tracker", "stats", source],
    queryFn: () => fetchStats(source), refetchInterval: STATIC_MS, enabled });
}

/** The stock panel. Only fetched while a symbol is selected. */
export function useStock(symbol: string | null) {
  return useQuery({ queryKey: ["nse-tracker", "stock", symbol],
    queryFn: () => fetchStock(symbol as string), enabled: Boolean(symbol),
    refetchInterval: DAILY_MS });
}

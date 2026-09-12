"use client";

import { useQuery } from "@tanstack/react-query";

import {
  fetchPaperTrades,
  fetchReturns,
  fetchStatus,
  fetchTournament,
} from "./api";

/**
 * The recorder polls the chain every fifteen seconds and the launch feed runs
 * continuously, so thirty seconds keeps the board close to live without
 * issuing requests faster than the numbers can move.
 */
const REFRESH_MS = 30_000;

/**
 * Why every query here overrides the app-wide defaults.
 *
 * Two behaviours combine to freeze this page. React Query SUSPENDS
 * `refetchInterval` while the document is hidden, so polling stops the moment
 * you switch tabs — and the app then turns `refetchOnWindowFocus` off for
 * healthy queries, on the reasoning that "the live stream already pushes
 * changes". That is true of the screens it was written for. It is not true
 * here: nothing pushes the graduation lab, every figure on it is polled, and
 * the tournament closes trades continuously whether or not anyone is looking.
 *
 * The result was a page whose numbers were correct when you left and frozen
 * when you came back — observed live, stuck at 211 closed trades while the
 * database held 612.
 *
 * So: refetch on focus, and never serve a cached figure to a returning
 * reader. Polling still pauses while the tab is hidden, which is right — no
 * one is reading it, and the answer is fetched the instant they are.
 */
const LIVE = {
  refetchOnWindowFocus: true,
  staleTime: 0,
} as const;

export function useGraduationStatus() {
  return useQuery({
    queryKey: ["graduation", "status"],
    queryFn: fetchStatus,
    refetchInterval: REFRESH_MS,
    ...LIVE,
  });
}

/**
 * The full trade history. Slower than the board on purpose: a closed trade
 * never changes, so the only new information is the odd exit, and the book
 * ticks once a minute.
 */
export function useGraduationTrades(book: string) {
  return useQuery({
    queryKey: ["graduation", "paper-trades", book],
    queryFn: () => fetchPaperTrades(book),
    refetchInterval: 60_000,
    ...LIVE,
  });
}

/**
 * The peak-multiple distribution. Five minutes: it is a population summary
 * over weeks of recording and does not move on a thirty-second timescale.
 */
export function useGraduationReturns() {
  return useQuery({
    queryKey: ["graduation", "returns"],
    queryFn: fetchReturns,
    refetchInterval: 300_000,
    ...LIVE,
  });
}

/**
 * The leaderboard. Thirty seconds, like the board: this is the number the
 * tournament exists to show and it moves every time an arm closes a trade.
 */
export function useGraduationTournament() {
  return useQuery({
    queryKey: ["graduation", "tournament"],
    queryFn: fetchTournament,
    refetchInterval: 30_000,
    ...LIVE,
  });
}

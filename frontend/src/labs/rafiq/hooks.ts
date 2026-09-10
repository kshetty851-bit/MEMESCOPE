"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchKarthikWallet } from "@/lib/karthik";

import {
  fetchRafiqBreaker,
  fetchRafiqPositions,
  fetchRafiqStatus,
  fetchRafiqTrades,
} from "./api";

/**
 * Polled on the lab's cadence, not the market's. The lab decides once a
 * minute, so a faster refetch would issue requests to observe a number that
 * cannot have changed.
 *
 * The Karthik wallet is fetched from ITS OWN endpoint, side by side. The
 * comparison happens here, in the browser, precisely because the backend lab
 * is forbidden from reading the existing wallet's tables — so the two columns
 * are two independent reads of two independent ledgers, which is what makes
 * them honest to put next to each other.
 */
const POLL_MS = 60_000;

export function useRafiqStatus() {
  return useQuery({ queryKey: ["rafiq", "status"], queryFn: fetchRafiqStatus,
    refetchInterval: POLL_MS });
}

export function useRafiqPositions() {
  return useQuery({ queryKey: ["rafiq", "positions"], queryFn: fetchRafiqPositions,
    refetchInterval: POLL_MS });
}

export function useRafiqTrades() {
  return useQuery({ queryKey: ["rafiq", "trades"], queryFn: fetchRafiqTrades,
    refetchInterval: POLL_MS });
}

export function useRafiqBreaker() {
  return useQuery({ queryKey: ["rafiq", "breaker"], queryFn: fetchRafiqBreaker,
    refetchInterval: POLL_MS });
}

/** The existing wallet, read from its own API for the comparison column. */
export function useKarthikComparison() {
  return useQuery({ queryKey: ["karthik", "wallet"], queryFn: fetchKarthikWallet,
    refetchInterval: POLL_MS });
}

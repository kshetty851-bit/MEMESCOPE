"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  fetchScoreHistory,
  fetchScoringModel,
  fetchTokenScore,
  fetchTopScores,
} from "@/lib/scores";
import type { TokenScore } from "@/types/score";

/**
 * AI scores for the live window, keyed by mint.
 *
 * **One request serves every consumer.** The Core, the discovery feed, the
 * squad panels and the Observatory Log all need a score per token; each calling
 * this hook shares a single `["scores", "window"]` query through TanStack
 * Query's cache, so a page with a dozen scored cards still issues exactly one
 * request per refresh instead of one per card.
 *
 * Vetoed tokens are included deliberately. The ranking endpoint hides them by
 * default because they do not belong in a list of opportunities, but the feed
 * has to be able to show a token the risk gate has just condemned — that is
 * among the most important things it can tell a user.
 */
export function useScoresByMint(pollMs = 20_000) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["scores", "window"],
    queryFn: () =>
      fetchTopScores({ pageSize: 100, sort: "evaluated_at", includeVetoed: true }),
    refetchInterval: pollMs,
    staleTime: pollMs / 2,
  });

  const byMint = useMemo(() => {
    const map = new Map<string, TokenScore>();
    for (const entry of data?.items ?? []) {
      map.set(entry.token.mint_address, entry.score);
    }
    return map;
  }, [data]);

  /**
   * Display names for the same rows.
   *
   * The ranking response already carries `token.name` and `token.symbol`; this
   * hook used to discard them and keep only the score. Consumers that needed a
   * name then had to find the mint in the discovery feed, which only holds the
   * most recent arrivals — so a token scored an hour ago rendered as a
   * truncated address despite its name sitting in the payload all along.
   */
  const labelsByMint = useMemo(() => {
    const map = new Map<string, string>();
    for (const entry of data?.items ?? []) {
      const label = entry.token.symbol ?? entry.token.name;
      if (label) map.set(entry.token.mint_address, label);
    }
    return map;
  }, [data]);

  return { byMint, labelsByMint, isPending, isError, total: data?.total ?? 0 };
}

/**
 * The highest-scoring tokens, for the curated rail.
 *
 * A separate query from the window above because it asks a different question —
 * "what is best right now?" rather than "what has just been re-scored?" — and
 * the two want different sort orders. Ranking excludes vetoed tokens, which is
 * the endpoint's default.
 */
export function useTopScores(pageSize = 6, pollMs = 30_000) {
  return useQuery({
    queryKey: ["scores", "top", pageSize],
    queryFn: () => fetchTopScores({ pageSize, sort: "score", order: "desc" }),
    refetchInterval: pollMs,
    staleTime: pollMs / 2,
  });
}

/**
 * One token's full score, including the component waterfall and reasons.
 *
 * The ranking endpoint omits the breakdown because it is kilobytes per token
 * and a list is scanned rather than read; the detail view fetches it here.
 */
export function useTokenScore(mint: string | undefined, pollMs = 20_000) {
  return useQuery({
    queryKey: ["scores", "token", mint],
    queryFn: () => fetchTokenScore(mint!),
    enabled: Boolean(mint),
    refetchInterval: pollMs,
  });
}

export function useScoreHistory(mint: string | undefined, pageSize = 25) {
  return useQuery({
    queryKey: ["scores", "history", mint, pageSize],
    queryFn: () => fetchScoreHistory(mint!, pageSize),
    enabled: Boolean(mint),
    staleTime: 30_000,
  });
}

/**
 * The active model's weights and thresholds.
 *
 * Static for the lifetime of a deploy, so it is fetched once and never
 * refetched. Publishing it is what lets the UI state honestly that a component
 * is declared but has no data source yet, rather than silently omitting it.
 */
export function useScoringModel() {
  return useQuery({
    queryKey: ["scores", "model"],
    queryFn: fetchScoringModel,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

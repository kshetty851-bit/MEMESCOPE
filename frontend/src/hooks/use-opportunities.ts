"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchOpportunities } from "@/lib/opportunities";
import type { OpportunityStage } from "@/types/opportunity";

/**
 * The live opportunity board.
 *
 * Polled every sixty seconds. Detection rides enrichment writes, so a
 * fresh-tier token can produce a signal within thirty seconds while an
 * old-tier one takes hours — a minute sits close enough to the fastest cadence
 * to feel live without issuing sixty requests to observe one change.
 *
 * `staleTime` is half the interval so a tab regaining focus mid-cycle refetches
 * rather than showing a card the board may already have dropped.
 */

export const BOARD_POLL_MS = 60_000;

export function useOpportunities(
  params: { signalType?: string | null; stage?: OpportunityStage | null } = {},
) {
  return useQuery({
    // Only the server-side filters belong in the key. Search, confidence,
    // priority and sorting are applied client-side over this page, so keying on
    // them would refetch identical data on every keystroke.
    queryKey: ["opportunities", "board", params.signalType ?? null, params.stage ?? null],
    queryFn: () => fetchOpportunities(params),
    refetchInterval: BOARD_POLL_MS,
    staleTime: BOARD_POLL_MS / 2,
  });
}

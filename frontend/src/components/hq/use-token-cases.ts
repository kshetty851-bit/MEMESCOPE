"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useLiveUpdates } from "@/hooks/use-live-updates";
import { usePaperPositions } from "@/hooks/use-paper";
import { useRadar, useRadarEntry } from "@/hooks/use-radar";
import { deriveCaseFile, type CaseSources, type TokenCaseFile } from "@/lib/hq/case-file";
import { selectPackets, type PacketSelection } from "@/lib/hq/packets";
import {
  fetchPaperDecisions,
  fetchTokenSecurity,
  type PaperDecisions,
  type TokenSecurityEvaluations,
} from "@/lib/hq/pipeline";
import { createRecentMintTracker } from "@/lib/hq/recent-mints";
import type { Source } from "@/lib/hq/adapter";

/**
 * THE TOKEN-CASE QUERY LAYER.
 *
 * HQ-4's rule again: components read normalized data, and exactly one place
 * owns the network. Four sources feed a case file — three of them are the
 * app's existing hooks (`useRadarEntry`, `usePaperPositions`, `useRadar`), so
 * a Case File panel open next to the Opportunity board costs no extra
 * requests. Only the per-mint safety read is new, and it is scoped exactly
 * where §29 requires: a visible packet, or an explicitly opened case,
 * never a whole page of tokens.
 */

const SAFETY_POLL_MS = 120_000;
const DECISION_POLL_MS = 180_000;
const RECENT_RADAR_PAGE_SIZE = 20;

function sourceOf<T>(query: {
  data: T | undefined;
  dataUpdatedAt: number;
  isError: boolean;
}): Source<T> {
  return {
    data: query.data ?? null,
    observedAt: query.dataUpdatedAt > 0 ? query.dataUpdatedAt : null,
    failed: query.isError && query.data === undefined,
  };
}

/**
 * Per-mint security and decision evidence, fetched only when `mint` is
 * non-null — i.e. for one explicitly opened case file or one visible packet.
 *
 * `enabled: mint !== null` is the N+1 guard and it is the whole guard. There
 * is no code path anywhere in HQ that maps over a list of mints calling
 * these; a page of Radar rows that wants security in bulk must use
 * `GET /token-security/evaluations?mints=` , which is bounded server-side.
 */
function useTokenSecurity(mint: string | null) {
  return useQuery({
    queryKey: ["hq", "token-security", mint],
    queryFn: () => fetchTokenSecurity(mint!),
    enabled: mint !== null,
    staleTime: SAFETY_POLL_MS / 2,
    refetchInterval: mint !== null ? SAFETY_POLL_MS : false,
  });
}

/**
 * The engine's own verdict for this mint.
 *
 * Polled more slowly than security: a decision is a record of a past pass and
 * does not change once written, so the only reason to refetch at all is to
 * pick up a *new* verdict from a later pass.
 */
function usePaperDecisions(mint: string | null) {
  return useQuery({
    queryKey: ["hq", "paper-decisions", mint],
    queryFn: () => fetchPaperDecisions(mint!),
    enabled: mint !== null,
    staleTime: DECISION_POLL_MS / 2,
    refetchInterval: mint !== null ? DECISION_POLL_MS : false,
  });
}

/** One token's full case file. `mint === null` renders the all-UNAVAILABLE default. */
export function useTokenCaseFile(mint: string | null): TokenCaseFile {
  const radar = useRadarEntry(mint ?? undefined);
  const positions = usePaperPositions();
  const security = useTokenSecurity(mint);
  const decisions = usePaperDecisions(mint);
  const now = useNow();

  return useMemo(() => {
    const sources: Partial<CaseSources> = {
      radar: sourceOf(radar),
      paperPositions: sourceOf(positions),
      tokenSecurity: sourceOf(security) as Source<TokenSecurityEvaluations>,
      decisions: sourceOf(decisions) as Source<PaperDecisions>,
      now,
    };
    return deriveCaseFile(mint ?? "", sources);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    mint,
    radar.dataUpdatedAt,
    radar.isError,
    positions.dataUpdatedAt,
    positions.isError,
    security.dataUpdatedAt,
    security.isError,
    decisions.dataUpdatedAt,
    decisions.isError,
    now,
  ]);
}

/** Re-renders on a slow tick so freshness windows resolve without a subscription. */
function useNow(intervalMs = 15_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const handle = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(handle);
  }, [intervalMs]);
  return now;
}

/**
 * The office's live token journey: up to three visible packets, from real
 * activity only. See `packets.ts` for the selection rule.
 */
export function useVisiblePackets(): PacketSelection {
  const { subscribe } = useLiveUpdates();
  const recentRadar = useRadar({ sort: "detected", pageSize: RECENT_RADAR_PAGE_SIZE });
  const positions = usePaperPositions();

  const trackerRef = useRef(createRecentMintTracker());
  const [transitioning, setTransitioning] = useState<string[]>([]);

  useEffect(() => {
    const tracker = trackerRef.current;
    const unsubscribe = subscribe((event) => {
      tracker.observe(event, Date.now());
    });
    // A slow tick, matching HQ-4's flush cadence — bounded re-renders under a
    // storm, never one render per event.
    const handle = window.setInterval(() => {
      setTransitioning(tracker.snapshot(Date.now()));
    }, 3_000);
    return () => {
      unsubscribe();
      window.clearInterval(handle);
    };
  }, [subscribe]);

  return useMemo(
    () =>
      selectPackets(
        {
          transitioning,
          recentRadar: sourceOf(recentRadar),
          recentPositions: sourceOf(positions),
        },
        Date.now(),
      ),
    // Keyed on the update stamps rather than the query objects themselves,
    // same reasoning as `useTokenCaseFile` above: identity churns every
    // render, the stamps only change when there is new data to react to.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [transitioning, recentRadar.dataUpdatedAt, recentRadar.isError, positions.dataUpdatedAt, positions.isError],
  );
}

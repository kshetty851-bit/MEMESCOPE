"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useLiveUpdates } from "@/hooks/use-live-updates";
import { usePaperAudit, usePaperPositions, usePaperWallet } from "@/hooks/use-paper";
import { useRadarPerformance } from "@/hooks/use-radar";
import {
  deriveHqState,
  react,
  witness,
  type HqState,
  type HqWitness,
  type Source,
  type Transient,
} from "@/lib/hq/adapter";
import { createEventMeter, emptyActivity, type EventActivity } from "@/lib/hq/events";
import {
  fetchExecutionPosture,
  fetchPipelineHealth,
  fetchTokenSecuritySummary,
} from "@/lib/hq/pipeline";
import type { EmployeeId } from "@/lib/hq/employees";

/**
 * THE ONE PLACE HQ TOUCHES THE NETWORK.
 *
 * Five queries feed the whole office. Four of them are the app's existing hooks
 * — the same query keys the wallet and radar screens already use, so opening HQ
 * with another tab open costs no extra requests and both screens share one
 * cache entry. Only pipeline health is new, because nothing else asks for it.
 *
 * WHY PIPELINE HEALTH POLLS EVEN ON A LIVE SOCKET
 *
 * Every other query here uses `livePoll`, which disables the timer while the
 * stream is connected — correct, because the stream invalidates those keys when
 * their data changes. Nothing on the stream announces a stage going degraded.
 * A pipeline query on `livePoll` would therefore fetch once, never refetch, and
 * age past its freshness window into UNKNOWN about ninety seconds later. So it
 * keeps a plain interval. React Query pauses it while the tab is hidden, which
 * is the visibility behaviour HQ-3 established, for free.
 *
 * WHY THE EVENT METER IS NOT REACT STATE
 *
 * Events arrive faster than anyone should render. The meter is a ref, written
 * on every arrival at whatever rate the stream runs, and read on a slow timer.
 * That timer is the only thing that decides how often HQ re-renders — a
 * hundred `market.changed` in three seconds produce one busy market desk and at
 * most one render, which is the storm protection the plan asks for, expressed
 * as an architecture rather than as a debounce sprinkled over a component.
 */

/**
 * How often pipeline health is re-read.
 *
 * The endpoint runs half a dozen aggregate queries and its own docstring warns
 * against pointing a fast check at it. A minute is far slower than anything the
 * room animates on — the liveness comes from the stream — and slow enough that
 * HQ is not a load source.
 */
const PIPELINE_POLL_MS = 60_000;

/**
 * How often the aggregated stream reading reaches React.
 *
 * The upper bound on HQ's render rate from events: twenty a minute, whatever
 * the stream does. It also advances the clock the adapter uses, so freshness
 * expiry and reaction timeouts resolve within one tick.
 */
const FLUSH_MS = 3_000;

/**
 * How often Atlas's aggregate is re-read.
 *
 * Same reasoning as pipeline health, one step slower. Nothing on the live
 * stream announces a security evaluation, so this cannot ride `livePoll` or it
 * would fetch once and then age into UNKNOWN. The underlying evidence is
 * written at most once per paper review pass, so polling faster than the
 * evidence changes would be load without information.
 */
const TOKEN_SECURITY_POLL_MS = 120_000;

interface QueryLike<T> {
  data: T | undefined;
  dataUpdatedAt: number;
  isError: boolean;
}

/**
 * A query, as the adapter wants to see it.
 *
 * `failed` is deliberately "errored *and* holding nothing". React Query keeps
 * the last good value through a failed refetch, and blanking the office on one
 * blip would be its own kind of dishonesty — the staleness window in the
 * adapter is what turns a source that has genuinely stopped arriving into
 * UNKNOWN, and it does that whether or not anyone saw an error.
 */
function sourceOf<T>(query: QueryLike<T>): Source<T> {
  return {
    data: query.data ?? null,
    observedAt: query.dataUpdatedAt > 0 ? query.dataUpdatedAt : null,
    failed: query.isError && query.data === undefined,
  };
}

export function useHqState(): HqState {
  const { status: stream, subscribe } = useLiveUpdates();

  const pipeline = useQuery({
    queryKey: ["health", "pipeline"],
    queryFn: fetchPipelineHealth,
    refetchInterval: PIPELINE_POLL_MS,
    staleTime: PIPELINE_POLL_MS / 2,
  });
  const tokenSecurity = useQuery({
    queryKey: ["token-security", "summary"],
    queryFn: fetchTokenSecuritySummary,
    refetchInterval: TOKEN_SECURITY_POLL_MS,
    staleTime: TOKEN_SECURITY_POLL_MS / 2,
  });
  // Posture changes only when an operator changes configuration or trips a
  // kill switch, neither of which the stream announces. Polled, slowly.
  const executionPosture = useQuery({
    queryKey: ["real-wallet-safety", "execution-posture"],
    queryFn: fetchExecutionPosture,
    refetchInterval: TOKEN_SECURITY_POLL_MS,
    staleTime: TOKEN_SECURITY_POLL_MS / 2,
  });
  const paperWallet = usePaperWallet();
  const paperPositions = usePaperPositions();
  const paperAudit = usePaperAudit();
  const radarPerformance = useRadarPerformance();

  /* ---- aggregated stream pressure ------------------------------------ */

  const meterRef = useRef<ReturnType<typeof createEventMeter> | null>(null);
  const [pulse, setPulse] = useState<{ activity: EventActivity; now: number }>(() => ({
    activity: emptyActivity(),
    now: Date.now(),
  }));

  useEffect(() => {
    const meter = createEventMeter(Date.now());
    meterRef.current = meter;
    const unsubscribe = subscribe((event) => meter.record(event.type, Date.now()));
    const flush = () => {
      const now = Date.now();
      setPulse({ activity: meter.snapshot(now), now });
    };
    flush();
    const handle = window.setInterval(flush, FLUSH_MS);
    return () => {
      unsubscribe();
      window.clearInterval(handle);
      meterRef.current = null;
    };
  }, [subscribe]);

  /* ---- reactions to things that actually happened --------------------- */

  const witnessRef = useRef<HqWitness | null>(null);
  const [transients, setTransients] = useState<Partial<Record<EmployeeId, Transient>>>({});

  const sources = useMemo(
    () => ({
      pipeline: sourceOf(pipeline),
      paperWallet: sourceOf(paperWallet),
      paperPositions: sourceOf(paperPositions),
      paperAudit: sourceOf(paperAudit),
      radarPerformance: sourceOf(radarPerformance),
      tokenSecurity: sourceOf(tokenSecurity),
      executionPosture: sourceOf(executionPosture),
    }),
    // Identity of the query objects changes on every render; their update
    // stamps do not. Keying on the stamps is what stops this from rebuilding
    // the source bundle — and therefore re-deriving the office — on every
    // unrelated render in the tree.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      pipeline.dataUpdatedAt,
      pipeline.isError,
      paperWallet.dataUpdatedAt,
      paperWallet.isError,
      paperPositions.dataUpdatedAt,
      paperPositions.isError,
      paperAudit.dataUpdatedAt,
      paperAudit.isError,
      radarPerformance.dataUpdatedAt,
      radarPerformance.isError,
      tokenSecurity.dataUpdatedAt,
      tokenSecurity.isError,
      executionPosture.dataUpdatedAt,
      executionPosture.isError,
    ],
  );

  useEffect(() => {
    const next = witness(sources);
    const previous = witnessRef.current;
    witnessRef.current = next;
    const reactions = react(previous, next, Date.now());
    if (Object.keys(reactions).length === 0) return;
    setTransients((current) => ({ ...current, ...reactions }));
  }, [sources]);

  /* ---- one normalized office ----------------------------------------- */

  return useMemo(
    () =>
      deriveHqState({
        ...sources,
        activity: pulse.activity,
        stream,
        transients,
        now: pulse.now,
      }),
    [sources, pulse, stream, transients],
  );
}

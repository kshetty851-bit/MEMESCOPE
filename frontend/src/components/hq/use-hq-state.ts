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
import { fetchHqOperations } from "@/lib/hq/operations";
import { fetchKarthik, readLastVisit, writeLastVisit } from "@/lib/hq/karthik";
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

/**
 * How often the operations surface is re-read.
 *
 * The fastest poll in HQ, and the only one that is fast on purpose. This is
 * the source whose entire job is to notice that something stopped, and the
 * autonomous tick behind it runs every two minutes — reading slower than the
 * thing that acts would mean the room routinely shows a repair that already
 * happened as work still pending.
 *
 * Still one request. The endpoint aggregates health, incidents, the audit
 * trail and the allowlist precisely so this does not become six.
 */
const OPERATIONS_POLL_MS = 45_000;

/**
 * How often Karthik's surface is re-read.
 *
 * A minute. Slower than `operations` because nothing here is a liveness watch
 * — the infrastructure half of Karthik's health screen comes from the same
 * `hq_ops` probe that surface already polls faster — and faster than the paper
 * endpoints because the reactions in §18 are derived from *changes* in this
 * response, and a target hit that reaches the room two minutes late reads as a
 * celebration for nothing.
 *
 * Still one request. The endpoint aggregates six screens, the incident queue,
 * the action log, the allowlist, three reports and the while-away summary
 * precisely so this does not become eleven.
 */
const KARTHIK_POLL_MS = 60_000;

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
  const operations = useQuery({
    queryKey: ["hq", "operations"],
    queryFn: fetchHqOperations,
    refetchInterval: OPERATIONS_POLL_MS,
    staleTime: OPERATIONS_POLL_MS / 2,
  });
  /**
   * The reader's previous visit, read **once** on mount and then frozen.
   *
   * In a ref rather than in state, and deliberately not re-read: §13's summary
   * answers "what happened since you last looked", and if this were refreshed
   * on every render the window would collapse to zero within a second of the
   * page opening and the panel would permanently report that nothing had
   * happened. It is stamped forward on unmount instead, so the *next* visit
   * gets a real window.
   */
  const sinceRef = useRef<string | null>(null);
  if (sinceRef.current === null) sinceRef.current = readLastVisit();

  const karthik = useQuery({
    queryKey: ["karthik", "state"],
    queryFn: () => fetchKarthik(sinceRef.current),
    refetchInterval: KARTHIK_POLL_MS,
    staleTime: KARTHIK_POLL_MS / 2,
  });

  // Stamped on unmount rather than on arrival: a visit that is still open is
  // not a previous visit, and writing on arrival would make a reader who keeps
  // HQ in a background tab permanently unable to see what they missed.
  useEffect(() => {
    return () => writeLastVisit(new Date().toISOString());
  }, []);

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
      operations: sourceOf(operations),
      karthik: sourceOf(karthik),
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
      operations.dataUpdatedAt,
      operations.isError,
      karthik.dataUpdatedAt,
      karthik.isError,
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

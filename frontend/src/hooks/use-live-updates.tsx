"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

import { env } from "@/lib/env";
import type { PaperPositions } from "@/types/paper";
import type { RadarPage } from "@/types/radar";

export type LiveStreamStatus = "connecting" | "live" | "reconnecting" | "offline";

export type LiveEvent = {
  type: string;
  data?: { mint_address?: string };
  mints?: string[];
};

type LiveUpdates = {
  status: LiveStreamStatus;
  subscribe: (listener: (event: LiveEvent) => void) => () => void;
};

const LiveUpdatesContext = createContext<LiveUpdates | null>(null);
const OFFLINE_UPDATES: LiveUpdates = {
  status: "offline",
  subscribe: () => () => undefined,
};
const INITIAL_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;
const INVALIDATION_BATCH_MS = 150;

/**
 * The floor between two paper-wallet refreshes driven by live events.
 *
 * `paper.changed` reads like a rare, meaningful event — a trade happened — and
 * the original code treated it that way, invalidating the wallet, the positions
 * and the audit log immediately every time one arrived. It is not rare. The
 * market worker re-marks held positions on *every* committed observation and
 * announces `paper.changed` for each one, whether or not a position opened or
 * closed. Measured from the running stack: fifteen a minute, one every four
 * seconds. `market.changed` on a held mint is the same story, about once a
 * second.
 *
 * The paper endpoints take one to four seconds to answer, so those two rules
 * together refetched them faster than they could reply — a permanent duty cycle
 * on the slowest endpoints in the API, with each round of requests overlapping
 * the last.
 *
 * That is why the whole terminal felt broken rather than just the wallet. The
 * backend connection pool is shared, so queries that never stop asking starve
 * everything queued behind them: the scanner, the session probe, every other
 * screen. From the access log, `/paper/positions` degraded from ~1s to 78s
 * under its own refetch storm, at which point the dev proxy started resetting
 * sockets — which put the queries into an error state, which made them retry,
 * which added yet more load.
 *
 * Ten seconds is far tighter than the wallet's own 120s poll and nowhere near
 * often enough to saturate anything. A simulator whose review beat runs every
 * five minutes does not need its P&L re-read every four seconds.
 *
 * No trailing edge on purpose: both triggers fire continuously by construction,
 * so a suppressed refresh is always followed by another event within seconds,
 * and the 120s poll is the backstop if the stream stops entirely.
 */
const PAPER_REFRESH_MS = 10_000;

/**
 * The floor between two radar-list refreshes.
 *
 * Shorter than the paper limit because this is the screen people watch: the
 * scanner is the live surface of the product and it should feel like one.
 * Three seconds is still comfortably below the threshold where a human reads a
 * table as static, and it turns ~52 requests a minute into ~20.
 */
const RADAR_REFRESH_MS = 3_000;

/**
 * The close code the API sends when the alpha cookie is missing or invalid
 * (`ALPHA_WS_POLICY_VIOLATION_CODE` in `backend/app/api/v1/endpoints/tokens.py`,
 * which is the standard 1008 Policy Violation).
 *
 * This is the code that must **not** be retried. A refusal on policy grounds is
 * a decision, not a fault: the socket will be refused identically on the next
 * attempt and on every attempt after it, so backing off and trying again just
 * converts one refusal into an unbounded stream of them. Anything else — a
 * dropped connection, a restarted API, a flaky network — is transient and keeps
 * the existing exponential backoff.
 */
export const POLICY_VIOLATION_CODE = 1008;

function streamUrl(): string {
  const url = new URL(env.NEXT_PUBLIC_API_URL || window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/api/v1/tokens/stream";
  return url.toString();
}

function radarContainsMint(queryClient: ReturnType<typeof useQueryClient>, mints: Set<string>) {
  return queryClient
    .getQueriesData<RadarPage>({ queryKey: ["radar", "list"] })
    .some(([, page]) => page?.items.some((entry) => mints.has(entry.mint_address)));
}

function paperContainsMint(queryClient: ReturnType<typeof useQueryClient>, mints: Set<string>) {
  const positions = queryClient.getQueryData<PaperPositions>(["paper", "positions"]);
  return positions?.items.some((position) => mints.has(position.mint_address)) ?? false;
}

/**
 * The one browser connection for committed server updates.
 *
 * Redis already reaches every API process and the existing WebSocket endpoint
 * already reaches a process's clients. This provider only turns those event
 * identifiers into deduplicated active-query invalidations; it never computes
 * a market value, score, rank, or paper-wallet result in the browser.
 */
export function LiveUpdatesProvider({
  children,
  /**
   * Whether to hold a socket open at all.
   *
   * The stream is only useful inside the authenticated application, and the
   * API refuses it outright without an alpha cookie. Mounting the provider
   * with `enabled={false}` publishes an `offline` status — which every
   * consuming hook already treats as "fall back to polling" — without ever
   * touching the network.
   */
  enabled = true,
}: {
  children: ReactNode;
  enabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<LiveStreamStatus>(
    enabled ? "connecting" : "offline",
  );
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const closedByUsRef = useRef(false);
  const listenersRef = useRef(new Set<(event: LiveEvent) => void>());
  const pendingRef = useRef<LiveEvent[]>([]);
  const invalidateTimerRef = useRef<number | null>(null);
  const refreshedAtRef = useRef<Record<string, number>>({});

  /**
   * Whether an expensive group of queries may refetch again yet.
   *
   * The push model in this file assumed its events were occasional. Several of
   * them are continuous — the enrichment loop commits an observation roughly
   * once a second and every commit fans out into `market.changed`,
   * `radar.score_updated` and `paper.changed`. Invalidating on each one asked
   * the two slowest endpoint families in the API to refetch faster than they
   * could answer, and because the backend's connection pool is shared, that
   * starved every other screen too.
   *
   * Only the heavy groups are gated. Cheap keys stay immediate — a rate limit
   * on a 9ms request buys nothing and costs responsiveness.
   */
  const due = useCallback((group: string, ms: number) => {
    const now = Date.now();
    if (now - (refreshedAtRef.current[group] ?? 0) < ms) return false;
    refreshedAtRef.current[group] = now;
    return true;
  }, []);

  const flush = useCallback(() => {
    invalidateTimerRef.current = null;
    const events = pendingRef.current.splice(0);
    const marketMints = new Set<string>();
    const scoreMints = new Set<string>();
    const radarMints = new Set<string>();
    let freshDetectionsChanged = false;
    let radarChanged = false;
    let paperChanged = false;

    for (const event of events) {
      if (event.type === "token.discovered") {
        freshDetectionsChanged = true;
      } else if (event.type === "market.changed") {
        for (const mint of event.mints ?? []) marketMints.add(mint);
      } else if (event.type === "score.changed" && event.data?.mint_address) {
        scoreMints.add(event.data.mint_address);
      } else if (event.type === "radar.score_updated") {
        for (const mint of event.mints ?? []) radarMints.add(mint);
      } else if (event.type === "radar.changed" || event.type === "radar.ranking_changed") {
        radarChanged = true;
      } else if (event.type === "paper.changed") {
        paperChanged = true;
      }
    }

    for (const mint of marketMints) {
      void queryClient.invalidateQueries({
        queryKey: ["tokens", mint, "market"],
        refetchType: "active",
      });
      void queryClient.invalidateQueries({
        queryKey: ["tokens", mint, "history"],
        refetchType: "active",
      });
    }
    if (marketMints.size) {
      void queryClient.invalidateQueries({ queryKey: ["market", "recent"], refetchType: "active" });
      void queryClient.invalidateQueries({ queryKey: ["tokens", "fresh"], refetchType: "active" });
    }
    if (freshDetectionsChanged) {
      void queryClient.invalidateQueries({ queryKey: ["tokens", "fresh"], refetchType: "active" });
    }
    // A price tick on a listed mint. Measured on the running stack this fired
    // ~52 times a minute against a ~580ms endpoint — half the backend's
    // capacity spent re-reading a list to move a few numbers. Three seconds
    // still reads as live to a human and costs a seventeenth of the requests.
    if (
      marketMints.size &&
      radarContainsMint(queryClient, marketMints) &&
      due("radar", RADAR_REFRESH_MS)
    ) {
      void queryClient.invalidateQueries({ queryKey: ["radar", "list"], refetchType: "active" });
      void queryClient.invalidateQueries({ queryKey: ["radar", "entry"], refetchType: "active" });
    }
    if (scoreMints.size) {
      void queryClient.invalidateQueries({ queryKey: ["scores", "window"], refetchType: "active" });
      void queryClient.invalidateQueries({ queryKey: ["scores", "top"], refetchType: "active" });
      for (const mint of scoreMints) {
        void queryClient.invalidateQueries({
          queryKey: ["scores", "token", mint],
          refetchType: "active",
        });
      }
    }
    // Same list, same cost, same rate limit — a rescore arrives on the same
    // per-observation cadence as a price tick.
    if (
      radarMints.size &&
      radarContainsMint(queryClient, radarMints) &&
      due("radar", RADAR_REFRESH_MS)
    ) {
      void queryClient.invalidateQueries({ queryKey: ["radar", "list"], refetchType: "active" });
      void queryClient.invalidateQueries({ queryKey: ["radar", "entry"], refetchType: "active" });
    }
    if (radarChanged) {
      for (const key of [
        ["radar", "list"],
        ["radar", "entry"],
        ["radar", "performance"],
        ["radar", "benchmark"],
        ["radar", "timeline"],
      ]) {
        void queryClient.invalidateQueries({ queryKey: key, refetchType: "active" });
      }
    }
    /*
       Both paper triggers land here, behind one rate limit — see
       `PAPER_REFRESH_MS`. Neither is the rare event its name suggests: a price
       tick on a held mint and a "paper changed" re-mark both arrive every few
       seconds, and refetching three endpoints on each was what starved the
       rest of the app.

       The audit log is only worth re-reading on `paper.changed`; a price move
       cannot add a row to a permanent trade record.
    */
    const paperTouched =
      paperChanged || (marketMints.size > 0 && paperContainsMint(queryClient, marketMints));

    if (paperTouched && due("paper", PAPER_REFRESH_MS)) {
      const keys = paperChanged
        ? [["paper", "wallet"], ["paper", "positions"], ["paper", "audit"]]
        : [["paper", "wallet"], ["paper", "positions"]];
      for (const key of keys) {
        void queryClient.invalidateQueries({ queryKey: key, refetchType: "active" });
      }
    }
  }, [queryClient, due]);

  const dispatch = useCallback(
    (event: LiveEvent) => {
      for (const listener of listenersRef.current) listener(event);
      if (
        event.type !== "market.changed" &&
        event.type !== "token.discovered" &&
        event.type !== "score.changed" &&
        event.type !== "radar.score_updated" &&
        event.type !== "radar.changed" &&
        event.type !== "radar.ranking_changed" &&
        event.type !== "paper.changed"
      ) {
        return;
      }
      pendingRef.current.push(event);
      if (invalidateTimerRef.current === null) {
        invalidateTimerRef.current = window.setTimeout(flush, INVALIDATION_BATCH_MS);
      }
    },
    [flush],
  );

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    let socket: WebSocket;
    try {
      socket = new WebSocket(streamUrl());
    } catch {
      setStatus("offline");
      return;
    }
    socketRef.current = socket;

    socket.onopen = () => {
      retryRef.current = 0;
      setStatus("live");
    };
    socket.onmessage = (message) => {
      try {
        dispatch(JSON.parse(message.data as string) as LiveEvent);
      } catch {
        // A malformed frame is not a reason to lose a working stream.
      }
    };
    socket.onclose = (event?: { code?: number }) => {
      if (closedByUsRef.current) return;

      // Refused on policy grounds. Retrying cannot change the answer, so the
      // stream is marked offline and the consuming hooks fall back to their
      // polling intervals — which is a working product, just not a live one.
      //
      // `event` is optional because a real CloseEvent always carries a code but
      // a test double invoked bare does not, and a missing code must fall
      // through to the transient path rather than throw inside the handler.
      if (event?.code === POLICY_VIOLATION_CODE) {
        setStatus("offline");
        return;
      }

      setStatus("reconnecting");
      retryRef.current += 1;
      const capped = Math.min(INITIAL_RETRY_MS * 2 ** (retryRef.current - 1), MAX_RETRY_MS);
      timerRef.current = window.setTimeout(connect, Math.random() * capped);
    };
    socket.onerror = () => socket.close();
  }, [dispatch]);

  useEffect(() => {
    if (!enabled) {
      setStatus("offline");
      return;
    }

    closedByUsRef.current = false;
    connect();
    return () => {
      closedByUsRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      if (invalidateTimerRef.current) window.clearTimeout(invalidateTimerRef.current);
      socketRef.current?.close();
    };
  }, [connect, enabled]);

  const subscribe = useCallback((listener: (event: LiveEvent) => void) => {
    listenersRef.current.add(listener);
    return () => listenersRef.current.delete(listener);
  }, []);

  const value = useMemo(() => ({ status, subscribe }), [status, subscribe]);
  return <LiveUpdatesContext.Provider value={value}>{children}</LiveUpdatesContext.Provider>;
}

export function useLiveUpdates(): LiveUpdates {
  return useContext(LiveUpdatesContext) ?? OFFLINE_UPDATES;
}

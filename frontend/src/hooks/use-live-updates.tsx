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

function streamUrl(): string {
  const url = new URL(env.NEXT_PUBLIC_API_URL);
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
export function LiveUpdatesProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<LiveStreamStatus>("connecting");
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const closedByUsRef = useRef(false);
  const listenersRef = useRef(new Set<(event: LiveEvent) => void>());
  const pendingRef = useRef<LiveEvent[]>([]);
  const invalidateTimerRef = useRef<number | null>(null);

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
    if (marketMints.size && radarContainsMint(queryClient, marketMints)) {
      void queryClient.invalidateQueries({ queryKey: ["radar", "list"], refetchType: "active" });
      void queryClient.invalidateQueries({ queryKey: ["radar", "entry"], refetchType: "active" });
    }
    if (marketMints.size && paperContainsMint(queryClient, marketMints)) {
      void queryClient.invalidateQueries({ queryKey: ["paper", "wallet"], refetchType: "active" });
      void queryClient.invalidateQueries({ queryKey: ["paper", "positions"], refetchType: "active" });
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
    if (radarMints.size && radarContainsMint(queryClient, radarMints)) {
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
    if (paperChanged) {
      for (const key of [["paper", "wallet"], ["paper", "positions"], ["paper", "audit"]]) {
        void queryClient.invalidateQueries({ queryKey: key, refetchType: "active" });
      }
    }
  }, [queryClient]);

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
    socket.onclose = () => {
      if (closedByUsRef.current) return;
      setStatus("reconnecting");
      retryRef.current += 1;
      const capped = Math.min(INITIAL_RETRY_MS * 2 ** (retryRef.current - 1), MAX_RETRY_MS);
      timerRef.current = window.setTimeout(connect, Math.random() * capped);
    };
    socket.onerror = () => socket.close();
  }, [dispatch]);

  useEffect(() => {
    closedByUsRef.current = false;
    connect();
    return () => {
      closedByUsRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      if (invalidateTimerRef.current) window.clearTimeout(invalidateTimerRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

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

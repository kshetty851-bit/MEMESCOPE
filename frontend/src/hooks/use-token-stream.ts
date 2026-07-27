"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { env } from "@/lib/env";
import type { DiscoveredToken, TokenStreamEvent } from "@/types/api";

export type StreamStatus = "connecting" | "live" | "reconnecting" | "offline";

const MAX_BUFFERED = 100;
const INITIAL_RETRY_MS = 1000;
const MAX_RETRY_MS = 30_000;

function streamUrl(): string {
  // Derive ws:// or wss:// from the configured API origin rather than assuming
  // either — the scheme must follow the page, or browsers block the upgrade.
  const url = new URL(env.NEXT_PUBLIC_API_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/api/v1/tokens/stream";
  return url.toString();
}

/**
 * Subscribes to the live discovery feed.
 *
 * Reconnects with exponential backoff and jitter, mirroring the scanner's own
 * policy so a backend restart does not leave the page silently dead.
 */
export function useTokenStream(seed: DiscoveredToken[] = []) {
  const [tokens, setTokens] = useState<DiscoveredToken[]>(seed);
  const [status, setStatus] = useState<StreamStatus>("connecting");

  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUsRef = useRef(false);

  const seedKey = seed.map((token) => token.id).join(",");

  useEffect(() => {
    setTokens((current) => (current.length === 0 ? seed : current));
    // Only reseed when the seed itself changes identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedKey]);

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
      let event: TokenStreamEvent;
      try {
        event = JSON.parse(message.data as string) as TokenStreamEvent;
      } catch {
        return; // a malformed frame must not kill the feed
      }
      if (event.type !== "token.discovered") return;

      setTokens((current) => {
        // The scanner dedupes, but a reconnect can replay a token the page
        // already has; the list is the last line of defence.
        if (current.some((token) => token.mint_address === event.data.mint_address)) {
          return current;
        }
        return [event.data, ...current].slice(0, MAX_BUFFERED);
      });
    };

    socket.onclose = () => {
      if (closedByUsRef.current) return;
      setStatus("reconnecting");

      retryRef.current += 1;
      const capped = Math.min(INITIAL_RETRY_MS * 2 ** (retryRef.current - 1), MAX_RETRY_MS);
      const delay = Math.random() * capped;
      timerRef.current = setTimeout(connect, delay);
    };

    socket.onerror = () => socket.close();
  }, []);

  useEffect(() => {
    closedByUsRef.current = false;
    connect();

    return () => {
      closedByUsRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

  return { tokens, status };
}

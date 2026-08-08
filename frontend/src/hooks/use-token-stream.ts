"use client";

import { useEffect, useState } from "react";

import { useLiveUpdates } from "@/hooks/use-live-updates";
import type { DiscoveredToken, TokenStreamEvent } from "@/types/api";

export type StreamStatus = "connecting" | "live" | "reconnecting" | "offline";

const MAX_BUFFERED = 100;

/**
 * Subscribes to the live discovery feed.
 *
 * Reconnects with exponential backoff and jitter, mirroring the scanner's own
 * policy so a backend restart does not leave the page silently dead.
 */
export function useTokenStream(seed: DiscoveredToken[] = []) {
  const [tokens, setTokens] = useState<DiscoveredToken[]>(seed);
  const { status, subscribe } = useLiveUpdates();

  const seedKey = seed.map((token) => token.id).join(",");

  useEffect(() => {
    setTokens((current) => (current.length === 0 ? seed : current));
    // Only reseed when the seed itself changes identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedKey]);

  useEffect(() => {
    return subscribe((event) => {
      const discovery = event as TokenStreamEvent;
      if (discovery.type !== "token.discovered") return;
      setTokens((current) => {
        // The scanner dedupes, but a reconnect can replay a token the page
        // already has; the list is the last line of defence.
        if (current.some((token) => token.mint_address === discovery.data.mint_address)) {
          return current;
        }
        return [discovery.data, ...current].slice(0, MAX_BUFFERED);
      });
    });
  }, [subscribe]);

  return { tokens, status };
}

/**
 * WHICH MINTS THE LIVE STREAM JUST TOUCHED.
 *
 * A sibling to HQ-4's `events.ts`, not an extension of it — that meter counts
 * *kinds* of event for the office's operational reading and must stay exactly
 * that; token packets are a different concern with a different consumer, and
 * coupling them would mean a change to one risks silently mis-sizing the
 * other's cap.
 *
 * Same storm-safety shape as HQ-4's meter: events are recorded on arrival,
 * cheaply, and the window is only evaluated on read. A hundred `market.changed`
 * touching the same ten mints in three seconds still yields ten mints, not a
 * hundred timestamps kept forever.
 */

import type { LiveEvent } from "@/hooks/use-live-updates";

/** How long a mint counts as "just touched". */
export const RECENT_MINT_WINDOW_MS = 20_000;

/** Most mints remembered at once, so a storm cannot grow this without bound. */
const RECENT_MINT_CAP = 40;

export interface RecentMintTracker {
  /** Record whatever mints one live event names. Cheap; call on every message. */
  observe(event: LiveEvent, now: number): void;
  /** Mints touched inside the window, most recent first. */
  snapshot(now: number): string[];
}

function mintsOf(event: LiveEvent): string[] {
  if (event.mints && event.mints.length > 0) return event.mints;
  if (event.data?.mint_address) return [event.data.mint_address];
  return [];
}

export function createRecentMintTracker(): RecentMintTracker {
  const lastSeen = new Map<string, number>();

  function trim(now: number) {
    for (const [mint, at] of lastSeen) {
      if (now - at > RECENT_MINT_WINDOW_MS) lastSeen.delete(mint);
    }
    if (lastSeen.size <= RECENT_MINT_CAP) return;
    const oldestFirst = [...lastSeen.entries()].sort((a, b) => a[1] - b[1]);
    for (const [mint] of oldestFirst.slice(0, lastSeen.size - RECENT_MINT_CAP)) {
      lastSeen.delete(mint);
    }
  }

  return {
    observe(event, now) {
      for (const mint of mintsOf(event)) lastSeen.set(mint, now);
      trim(now);
    },
    snapshot(now) {
      trim(now);
      return [...lastSeen.entries()].sort((a, b) => b[1] - a[1]).map(([mint]) => mint);
    },
  };
}

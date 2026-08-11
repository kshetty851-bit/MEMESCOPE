"use client";

import { useSyncExternalStore } from "react";

/**
 * ONE CLOCK FOR THE WHOLE PAGE.
 *
 * `FreshnessLabel` used to open its own `setInterval` per instance. That was
 * fine for a page showing ten cards. The scanner shows fifty rows, each with a
 * freshness indicator, and every one of those readings is under a minute old on
 * a healthy pipeline — so the per-instance cadence is 1s and the page ends up
 * running fifty independent one-second timers, each waking React separately.
 *
 * This is one timer for the document, with subscribers. Fifty indicators now
 * cost one wakeup per second instead of fifty, and they all re-render in the
 * same commit rather than in fifty staggered ones.
 *
 * The cadence is the fastest any subscriber asked for, recomputed whenever the
 * set changes: a page showing only hour-old readings ticks every 30s, and one
 * showing a live row ticks every second, without either having to know about
 * the other.
 */

type Subscriber = { cadence: number; notify: () => void };

const subscribers = new Set<Subscriber>();
let timer: ReturnType<typeof setInterval> | null = null;
let activeCadence = 0;
let snapshot = Date.now();

function fastestCadence(): number {
  let fastest = Infinity;
  for (const subscriber of subscribers) {
    if (subscriber.cadence < fastest) fastest = subscriber.cadence;
  }
  return Number.isFinite(fastest) ? fastest : 0;
}

function retime(): void {
  const wanted = fastestCadence();
  if (wanted === activeCadence) return;

  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
  activeCadence = wanted;
  if (wanted === 0) return;

  timer = setInterval(() => {
    snapshot = Date.now();
    for (const subscriber of subscribers) subscriber.notify();
  }, wanted);
}

function subscribeAt(cadence: number) {
  return (notify: () => void) => {
    const subscriber: Subscriber = { cadence, notify };
    subscribers.add(subscriber);
    retime();
    return () => {
      subscribers.delete(subscriber);
      retime();
    };
  };
}

/**
 * The shared "now", refreshed at least every `cadence` ms.
 *
 * Returns a timestamp rather than a tick counter so callers can derive an age
 * directly. During SSR it returns a fixed value; the first client render
 * corrects it, and a freshness label is not server-rendered content anyway.
 */
export function useSharedClock(cadence: number): number {
  return useSyncExternalStore(
    subscribeAt(cadence),
    () => snapshot,
    () => 0,
  );
}

/** Test seam: drops every subscriber and stops the timer. */
export function __resetSharedClock(): void {
  subscribers.clear();
  retime();
}

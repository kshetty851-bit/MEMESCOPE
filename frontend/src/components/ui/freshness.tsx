"use client";

import { useEffect, useState } from "react";

import { freshnessOf, newestOf, type FreshnessBand } from "@/lib/freshness";
import { cn } from "@/lib/utils";

/**
 * FRESHNESS, ON THE FACE OF THE ROW
 *
 * Sprint 28.1. The priority lane brought Top 10 freshness from ~169 minutes to
 * ~7 seconds, but a price is only as good as its timestamp — and some tokens
 * legitimately have no recent data because the provider indexes no pool for
 * them. Until this, a three-hour-old price and a seven-second-old price
 * rendered identically.
 *
 * The age is shown, never a "live" badge in its place. "Live" is a promise
 * about the future; a timestamp is a fact about the past, and only one of them
 * can be checked.
 */

const TONE: Record<FreshnessBand, string> = {
  fresh: "text-safe",
  normal: "text-ink-faint",
  ageing: "text-warn",
  stale: "text-danger",
  unknown: "text-ink-faint",
};

const DOT: Record<FreshnessBand, string> = {
  fresh: "bg-safe",
  normal: "bg-ink-faint",
  ageing: "bg-warn",
  stale: "bg-danger",
  unknown: "bg-line",
};

/**
 * Re-render on a timer so an age does not freeze at whatever it was when the
 * page rendered. One interval per mounted indicator, at the coarsest cadence
 * the label can change on: below a minute the label counts seconds, above it
 * only minutes.
 */
function useTick(ageSeconds: number | null): number {
  const [, setTick] = useState(0);
  const cadence = ageSeconds !== null && ageSeconds < 60 ? 1_000 : 30_000;

  useEffect(() => {
    const id = window.setInterval(() => setTick((value) => value + 1), cadence);
    return () => window.clearInterval(id);
  }, [cadence]);

  return Date.now();
}

/**
 * One reading's age. Compact by default; `withDot` for standalone use.
 *
 * A token that was never priced reads "No market data" rather than an age,
 * because nothing has gone stale if nothing was ever observed.
 */
export function FreshnessLabel({
  capturedAt,
  withDot = false,
  className,
}: {
  capturedAt: string | null | undefined;
  withDot?: boolean;
  className?: string;
}) {
  const initial = freshnessOf(capturedAt);
  const now = useTick(initial.ageSeconds);
  const freshness = freshnessOf(capturedAt, now);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-xs tabular-nums",
        TONE[freshness.band],
        className,
      )}
      title={freshness.description}
    >
      {withDot ? (
        <span
          aria-hidden
          className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[freshness.band])}
        />
      ) : null}
      <span className="sr-only">{freshness.description}</span>
      <span aria-hidden>{freshness.label}</span>
    </span>
  );
}

/**
 * The global badge: is the platform still receiving market data at all?
 *
 * Reports the **newest** reading across what is on screen, deliberately. This
 * answers a different question from per-row freshness — one recent reading
 * settles whether the pipeline is alive, while a single stale row does not mean
 * it is dead. Both questions are shown, in their own places, rather than
 * averaged into one number that answers neither.
 *
 * It never says "LIVE" on its own. The age is always beside it, because a badge
 * that says LIVE next to a three-minute-old price is the exact dishonesty this
 * sprint exists to remove.
 */
export function LiveStatus({
  timestamps,
  pending = false,
  className,
}: {
  timestamps: (string | null | undefined)[];
  /**
   * True while the page is still fetching. Renders nothing rather than
   * "No market data" — an empty array during load and an empty array because
   * nothing was ever observed are different states, and claiming the second
   * while the first is true is the dishonesty this component exists to remove.
   */
  pending?: boolean;
  className?: string;
}) {
  const initial = newestOf(timestamps);
  const now = useTick(initial.ageSeconds);
  const freshness = newestOf(timestamps, now);

  if (pending) return null;

  const receiving = freshness.band === "fresh" || freshness.band === "normal";
  const headline =
    freshness.band === "unknown"
      ? "No market data"
      : receiving
        ? "Live"
        : "Waiting for market data";

  return (
    <span
      className={cn("inline-flex items-center gap-2 text-xs", className)}
      title={freshness.description}
    >
      <span
        aria-hidden
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          DOT[freshness.band],
          receiving && "animate-pulse",
        )}
      />
      <span className={cn("font-medium", TONE[freshness.band])}>{headline}</span>
      {freshness.ageSeconds !== null ? (
        <span className="text-ink-faint">· {freshness.label.toLowerCase()}</span>
      ) : null}
    </span>
  );
}

/**
 * What to render instead of a price when there is no market at all.
 *
 * The audit found tokens the provider indexes no pool for — `consecutive_empty`
 * reached 34 on one of them. They are polled every fifteen seconds and still
 * return nothing. That is correct provider behaviour and a real state of the
 * token, so it is stated rather than papered over with the last price anyone
 * happened to see.
 */
export function NoMarketData({ className }: { className?: string }) {
  return (
    <span
      className={cn("text-xs text-ink-faint", className)}
      title="No pool has been indexed for this token, so no price is available. It is still being polled."
    >
      Waiting for liquidity
    </span>
  );
}

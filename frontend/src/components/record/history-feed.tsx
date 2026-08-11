"use client";

import { TokenIdentity } from "@/components/brand/token-identity";
import { Skeleton } from "@/components/ui/skeleton";
import { useRadarTimeline } from "@/hooks/use-radar";
import type { RadarTimelineEvent } from "@/types/radar";

/**
 * HALL OF HISTORY
 *
 * The Radar's own history, newest first.
 *
 * Every line is a projection of a stored row — a detection or a tier crossing —
 * and carries that row's own timestamp. Nothing is authored for this feed, so
 * it can never claim an event the record does not contain, and it needs no
 * backfill when the record changes.
 *
 * Deliberately absent: "became inactive" and "dropped below entry". The first
 * needs a death rule the platform cannot defend; the second needs a crossing
 * event nothing currently records. Inventing either would put un-auditable
 * lines in the one feed whose value is that every line is checkable.
 */

const TIER_ICON: Record<string, string> = {
  "2x": "⭐",
  "5x": "⭐⭐",
  "10x": "⭐⭐⭐",
  "25x": "🏆",
  "50x": "🚀",
  "100x": "👑",
};

function ago(iso: string): string {
  const seconds = Math.max((Date.now() - new Date(iso).getTime()) / 1000, 0);
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}

function describe(event: RadarTimelineEvent): { icon: string; text: string } {
  const who = event.symbol ?? event.name ?? `${event.mint_address.slice(0, 6)}…`;
  if (event.kind === "achievement" && event.tier) {
    return {
      icon: TIER_ICON[event.tier] ?? "📈",
      text: `${who} reached ${event.tier.replace("x", "×")}`,
    };
  }
  return { icon: "🟢", text: `${who} detected` };
}

export function HistoryFeed() {
  const { data, isPending, isError } = useRadarTimeline(40);

  if (isError) {
    return (
      <p className="text-sm text-ink-3">
        The history feed is not responding. The record itself is intact — this is a
        read failure.
      </p>
    );
  }

  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-8" />
        ))}
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <p className="text-sm text-ink-3">
        Nothing recorded yet. Every detection and every milestone will appear here
        permanently.
      </p>
    );
  }

  return (
    <ol className="flex flex-col">
      {data.map((event) => {
        const { icon, text } = describe(event);
        return (
          <li
            // Tier is part of the key because a token that crosses 2× and 5× in
            // one sweep earns both milestones at the same instant — without it
            // React drops one of two real events.
            key={`${event.kind}-${event.mint_address}-${event.occurred_at}-${event.tier ?? ""}`}
            className="flex items-center gap-3 border-b border-line/50 py-2 last:border-0"
          >
            <span className="w-6 shrink-0 text-center" aria-hidden>
              {icon}
            </span>
            <div className="min-w-0 flex-1">
              <TokenIdentity
                mint={event.mint_address}
                name={event.name}
                symbol={event.symbol}
                imageUrl={event.image_url}
                size="xs"
                compact
              />
              <p className="mt-0.5 truncate text-xs text-ink-3">{text}</p>
            </div>
            <time
              dateTime={event.occurred_at}
              className="shrink-0 text-xs tabular-nums text-ink-3"
            >
              {ago(event.occurred_at)}
            </time>
          </li>
        );
      })}
    </ol>
  );
}

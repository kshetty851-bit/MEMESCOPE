"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { RadarRow } from "@/components/radar/radar-row";
import { StatusDot } from "@/components/ui/badge";
import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useRadar } from "@/hooks/use-radar";
import { sortRadarEntries, type RadarSortKey } from "@/lib/radar-row";
import { cn } from "@/lib/utils";

/**
 * THE RADAR — the homepage.
 *
 * One question: **what are today's best opportunities?** Ten rows, ranked by
 * the Radar score, each answering "should I care, why, and what usually
 * happened before" without leaving the row.
 *
 * Ten, not a hundred. The board this replaced returned a full page of a hundred
 * cards with more available; a ranked list nobody can finish is a leaderboard
 * wearing a recommendation's clothes. The whole record is still one click away
 * on the Track Record, where completeness is the point.
 *
 * **An empty Radar is a truthful Radar.** It means nothing currently clears the
 * model's floor, and it is never to be "fixed" by relaxing admission.
 */

const TOP_N = 10;

const SORTS: { key: RadarSortKey; label: string }[] = [
  { key: "score", label: "Radar score" },
  { key: "peak", label: "Peak" },
  { key: "current", label: "Current" },
  { key: "age", label: "Newest" },
];

export default function RadarPage() {
  const [sort, setSort] = useState<RadarSortKey>("score");

  // Ranked server-side by score; the page holds exactly what it shows. Sorting
  // re-orders those ten, and never silently swaps in an eleventh.
  const { data, isPending, isError, refetch, isFetching } = useRadar({
    pageSize: TOP_N,
    sort: "score",
  });

  const items = useMemo(() => data?.items ?? [], [data]);
  const visible = useMemo(() => sortRadarEntries(items, sort), [items, sort]);
  const total = data?.total ?? 0;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Radar</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            Today&apos;s best opportunities
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-dim">
            The top {TOP_N} of {total || "—"} tokens currently tracked, ranked by a
            deterministic score. Every figure below is measured; nothing is estimated,
            and nothing here is a prediction.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-faint">
          <StatusDot live={isFetching} tone="var(--color-plasma)" />
          <span>{isFetching ? "Refreshing" : "Every 2 min"}</span>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-1">
        {SORTS.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => setSort(option.key)}
            aria-pressed={sort === option.key}
            className={cn(
              "rounded-chip border px-2.5 py-1 text-xs transition-colors",
              sort === option.key
                ? "border-line-bright bg-elevated text-ink"
                : "border-line text-ink-faint hover:border-line-bright hover:text-ink",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      {isError ? (
        <ErrorState
          body="The Radar is not responding. Detections already recorded are safe — this view will recover on its own."
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-40 rounded-card" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          agent="scout"
          title="Nothing clears the bar right now"
          body="An empty Radar means no token currently meets the model's floor — not that the platform is idle. Every detection ever made is still on the Track Record."
          action={
            <Link
              href="/record"
              className="rounded-chip border border-line px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-line-bright hover:text-ink"
            >
              Open the track record
            </Link>
          }
        />
      ) : (
        <div className="flex flex-col gap-3">
          {visible.map((entry, index) => (
            <RadarRow key={entry.mint_address} entry={entry} rank={index + 1} />
          ))}
        </div>
      )}

      <Panel density="compact" className="border-line/60">
        <p className="text-xs leading-relaxed text-ink-dim">
          Base rates describe what happened to <em>past</em> detections in the same
          category. They are measured over the permanent record, losers included, and
          make no claim about any token above. Peak and current are always shown
          together — a call that reached 18× and fell to 0.30× is not an 18× call.
        </p>
        <Link
          href="/record"
          className="mt-2 inline-block text-xs text-ink-faint underline transition-colors hover:text-ink"
        >
          See every token we have ever detected
        </Link>
      </Panel>
    </div>
  );
}

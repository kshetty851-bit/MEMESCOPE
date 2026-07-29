"use client";

import Link from "next/link";
import { useState } from "react";

import { RadarCard } from "@/components/radar/radar-card";
import { Label, Panel } from "@/components/ui/panel";
import { SkeletonTokenCard } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useRadar, useRadarModel } from "@/hooks/use-radar";
import { CATEGORY_LABEL, CATEGORY_TONE } from "@/lib/radar";
import { cn } from "@/lib/utils";
import type { RadarCategory } from "@/types/radar";

/**
 * OPPORTUNITY RADAR
 *
 * The launch scanner answers "what appeared?". This answers "which projects are
 * getting stronger?" — of any age. A ninety-day-old token with growing
 * liquidity belongs here as much as a fresh launch, and nothing on this page
 * ranks by market cap.
 *
 * Categories that the current model cannot award are shown as disabled with the
 * reason, rather than silently omitted. A filter that can only ever return
 * nothing would imply the platform is looking for something it is not.
 */

type SortKey = "score" | "detected" | "peak" | "current";

const SORTS: { id: SortKey; label: string }[] = [
  { id: "score", label: "Score" },
  { id: "peak", label: "Peak return" },
  { id: "current", label: "Current return" },
  { id: "detected", label: "Newest" },
];

export default function RadarPage() {
  const [category, setCategory] = useState<RadarCategory | null>(null);
  const [sort, setSort] = useState<SortKey>("score");

  const model = useRadarModel();
  const { data, isPending, isError } = useRadar({ category, sort, pageSize: 24 });

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Opportunity Radar</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            Projects getting stronger
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-dim">
            Continuously re-evaluated regardless of age. Market cap is never a qualification
            — every return below is measured from the moment MEMESCOPE first detected the
            project, not from its launch.
          </p>
        </div>
        <Link
          href="/track-record"
          className="text-sm text-plasma transition-colors hover:text-ink"
        >
          See the full track record →
        </Link>
      </header>

      {/* --- Filters ------------------------------------------------------ */}
      <div className="flex flex-col gap-3">
        <div
          role="group"
          aria-label="Filter by category"
          className="flex flex-wrap gap-1.5"
        >
          <Chip active={category === null} onClick={() => setCategory(null)} label="All" />
          {model.data?.categories.map((spec) => (
            <Chip
              key={spec.id}
              active={category === spec.id}
              onClick={() => setCategory(spec.id)}
              label={CATEGORY_LABEL[spec.id]}
              tone={CATEGORY_TONE[spec.id]}
              disabled={!spec.reachable}
              title={spec.reachable_note ?? undefined}
            />
          ))}
        </div>

        <div role="group" aria-label="Sort" className="flex flex-wrap gap-1.5">
          {SORTS.map((option) => (
            <Chip
              key={option.id}
              active={sort === option.id}
              onClick={() => setSort(option.id)}
              label={option.label}
            />
          ))}
        </div>
      </div>

      {/* --- Results ------------------------------------------------------ */}
      {isError ? (
        <ErrorState
          body="The Radar is not responding. Detections already recorded are safe — this view will recover on its own."
          onRetry={() => window.location.reload()}
        />
      ) : isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <SkeletonTokenCard key={index} />
          ))}
        </div>
      ) : data.items.length === 0 ? (
        <EmptyState
          agent="oracle"
          title="Nothing on the Radar in this view"
          body={
            category === null
              ? "The Radar is deliberately selective — most projects never qualify. It re-evaluates continuously and will fill as projects strengthen."
              : "No project currently sits in this category. Try All, or another category."
          }
        />
      ) : (
        <>
          <p className="text-xs text-ink-faint">
            {data.total} {data.total === 1 ? "opportunity" : "opportunities"} on the Radar
          </p>
          <div className="grid items-start gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.items.map((entry) => (
              <RadarCard key={entry.mint_address} entry={entry} />
            ))}
          </div>
        </>
      )}

      {/* --- What the Radar cannot see ------------------------------------ */}
      {model.data && (
        <Panel density="compact" className="border-warn/20 bg-warn/[0.03]">
          <Label>What the Radar cannot see yet</Label>
          <p className="mt-2 text-sm leading-relaxed text-ink-dim">
            Community signals — social activity, development cadence, website uptime — are
            declared with real weight in the model but are not collected. They are counted
            against coverage rather than ignored, which is why confidence tops out at{" "}
            <span data-numeric className="font-mono text-ink">
              {Math.round(Number(model.data.available_weight_total) * 100)}%
            </span>{" "}
            and why <span className="text-ink">Strong Community</span> cannot currently be
            awarded.
          </p>
        </Panel>
      )}
    </div>
  );
}

function Chip({
  active,
  onClick,
  label,
  tone,
  disabled = false,
  title,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  tone?: string;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      title={title}
      className={cn(
        "rounded-chip border px-2.5 py-1 text-xs transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma",
        disabled && "cursor-not-allowed border-line/50 text-ink-faint/50",
        !disabled && active && "border-plasma/40 bg-plasma/12 text-plasma",
        !disabled &&
          !active &&
          "border-line text-ink-faint hover:border-line-bright hover:text-ink-dim",
      )}
      style={
        !disabled && active && tone
          ? {
              color: tone,
              borderColor: `color-mix(in oklch, ${tone} 40%, transparent)`,
              background: `color-mix(in oklch, ${tone} 12%, transparent)`,
            }
          : undefined
      }
    >
      {label}
      {disabled && <span className="ml-1 opacity-70">(no data)</span>}
    </button>
  );
}

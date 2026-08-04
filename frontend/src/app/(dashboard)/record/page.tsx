"use client";

import Link from "next/link";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useRadarPerformance } from "@/hooks/use-radar";
import { formatMultiple } from "@/lib/radar";
import { num } from "@/lib/scores";
import { cn } from "@/lib/utils";

/**
 * TRACK RECORD
 *
 * The platform's own performance, including its failures.
 *
 * This page is the argument for trusting anything else in the product, and it
 * only works if it is complete. Every project the Radar ever detected stays on
 * the record: the ones that went to zero are counted in the same denominator as
 * the ones that ran. A success rate computed only over the winners is not a
 * success rate, and a track record that quietly drops its losers is marketing.
 */

export default function TrackRecordPage() {
  const { data, isPending, isError } = useRadarPerformance();

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 pb-8">
      <header>
        <Label>Track record</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">
          How previous Radar opportunities actually performed
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-dim">
          Every project the Radar has ever detected, measured from the moment it was
          detected — never from launch. Failures are included and counted; nothing is
          removed once recorded.
        </p>
      </header>

      {isError ? (
        <ErrorState
          body="The track record is not responding. The record itself is append-only and intact — this is a read failure."
          onRetry={() => window.location.reload()}
        />
      ) : isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-24" />
          ))}
        </div>
      ) : data.total_opportunities === 0 ? (
        <EmptyState
          agent="oracle"
          title="No opportunities recorded yet"
          body="The Radar has not detected anything yet. Once it does, every detection appears here permanently — including the ones that do not work out."
        />
      ) : (
        <>
          {/* --- Headline figures ---------------------------------------- */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label="Total detected"
              value={data.total_opportunities.toLocaleString()}
              note="every entry, ever"
            />
            <Stat
              label="Currently active"
              value={data.active_opportunities.toLocaleString()}
              note="still being evaluated"
            />
            <Stat
              label="Reached 2× or more"
              value={
                data.success_rate === null
                  ? "—"
                  : `${(num(data.success_rate) * 100).toFixed(1)}%`
              }
              note="of everything detected"
              tone="positive"
            />
            <Stat
              label="Average peak"
              value={formatMultiple(data.average_peak_multiple)}
              note="mean best return"
            />
          </div>

          {/* --- Milestones ----------------------------------------------- */}
          <section>
            <Label>Milestones reached</Label>
            <p className="mt-1 text-sm text-ink-dim">
              Counted from each project&rsquo;s peak since detection. Once reached, a
              milestone is permanent — a project that touched 10× and fell back still
              touched 10×.
            </p>
            <div className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-9">
              {data.tiers.map((tier) => (
                <div
                  key={tier.tier}
                  className={cn(
                    "rounded-card border border-line bg-surface/50 px-2 py-3 text-center",
                    tier.count === 0 && "opacity-40",
                  )}
                >
                  <p data-numeric className="font-mono text-xs text-ink-faint">
                    {tier.tier}
                  </p>
                  <p data-numeric className="mt-1 font-mono text-lg text-ink">
                    {tier.count}
                  </p>
                </div>
              ))}
            </div>
          </section>

          {/* --- Best and worst, side by side ----------------------------- */}
          <div className="grid gap-4 sm:grid-cols-2">
            <Panel density="compact" accent="var(--color-safe)">
              <Label>Best opportunity</Label>
              <p data-numeric className="mt-1 font-mono text-2xl text-safe">
                {formatMultiple(data.best_peak_multiple)}
              </p>
              <p className="mt-1 text-xs text-ink-faint">highest peak from detection</p>
            </Panel>
            {/* Shown with equal prominence, deliberately. */}
            <Panel density="compact" accent="var(--color-danger)">
              <Label>Worst opportunity</Label>
              <p data-numeric className="mt-1 font-mono text-2xl text-danger">
                {formatMultiple(data.worst_current_multiple)}
              </p>
              <p className="mt-1 text-xs text-ink-faint">lowest current return</p>
            </Panel>
          </div>

          <Panel density="compact">
            <Label>Median current return</Label>
            <p data-numeric className="mt-1 font-mono text-xl text-ink-dim">
              {formatMultiple(data.median_current_multiple)}
            </p>
            <p className="mt-2 text-sm leading-relaxed text-ink-faint">
              The median is the honest middle: averages on this market are dominated by a
              handful of outliers, and quoting only the mean would describe a typical
              outcome nobody actually had.
            </p>
          </Panel>
        </>
      )}

      <div className="flex flex-wrap gap-4 border-t border-line/60 pt-4">
        <Link
          href="/"
          className="text-sm text-plasma transition-colors hover:text-ink"
        >
          ← Back to the Radar
        </Link>
        <Link
          href="/settings"
          className="text-sm text-ink-faint transition-colors hover:text-ink"
        >
          How scoring works
        </Link>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  tone?: "positive";
}) {
  return (
    <Panel density="compact">
      <Label>{label}</Label>
      <p
        data-numeric
        className={cn(
          "mt-1 font-mono text-2xl",
          tone === "positive" ? "text-safe" : "text-ink",
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-xs text-ink-faint">{note}</p>
    </Panel>
  );
}

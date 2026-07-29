"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Label, Panel } from "@/components/ui/panel";
import { Meter } from "@/components/ui/metric";
import { SkeletonText } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useRadarEntry, useRadarHistory } from "@/hooks/use-radar";
import { AGENTS, type AgentId } from "@/lib/design/agents";
import { formatUsd } from "@/lib/format";
import {
  CATEGORY_LABEL,
  CATEGORY_TONE,
  formatDays,
  formatMultiple,
  multipleTone,
} from "@/lib/radar";
import { num, ratio } from "@/lib/scores";
import { cn } from "@/lib/utils";

/**
 * RADAR TIMELINE
 *
 * One opportunity in full: what the engine saw, what it concluded, what has
 * happened since, and which milestones were reached along the way.
 *
 * The dimension breakdown is recomputed from the stored series on every
 * request, which is only possible because the engine is pure. That the same
 * inputs always give the same output is what makes this page an audit rather
 * than a summary.
 */

const TONE_CLASS = {
  positive: "text-safe",
  negative: "text-danger",
  neutral: "text-ink-faint",
} as const;

const SEVERITY_TONE: Record<string, string> = {
  positive: "var(--color-safe)",
  caution: "var(--color-warn)",
  critical: "var(--color-danger)",
  info: "var(--color-ink-faint)",
};

export default function RadarTimelinePage() {
  const params = useParams<{ mint: string }>();
  const mint = params?.mint;

  const { data, isPending, isError } = useRadarEntry(mint);
  const history = useRadarHistory(mint, 60);

  if (isError) {
    return (
      <ErrorState
        title="Not on the Radar"
        body="This token has never been detected by the Opportunity Radar, or the record could not be read."
        onRetry={() => window.location.reload()}
      />
    );
  }

  if (isPending || !data) {
    return (
      <Panel>
        <SkeletonText lines={10} />
      </Panel>
    );
  }

  const hue = CATEGORY_TONE[data.category];

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 pb-8">
      {/* --- Header ------------------------------------------------------- */}
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Label>Radar timeline</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            {data.symbol ?? data.name ?? "Unidentified"}
          </h1>
          <p data-numeric className="mt-1 break-all font-mono text-xs text-ink-faint">
            {data.mint_address}
          </p>
        </div>
        <span
          className="shrink-0 rounded-chip border px-2 py-1 text-xs font-semibold uppercase tracking-[0.1em]"
          style={{
            color: hue,
            borderColor: `color-mix(in oklch, ${hue} 35%, transparent)`,
            background: `color-mix(in oklch, ${hue} 10%, transparent)`,
          }}
        >
          {CATEGORY_LABEL[data.category]}
        </span>
      </header>

      {/* --- Performance since detection ---------------------------------- */}
      <Panel>
        <Label>Since MEMESCOPE first detected it</Label>
        <div className="mt-3 grid gap-4 sm:grid-cols-4">
          <Figure
            label="Current"
            value={formatMultiple(data.current_multiple)}
            tone={multipleTone(data.current_multiple)}
          />
          <Figure
            label="Peak"
            value={formatMultiple(data.peak_multiple)}
            tone={multipleTone(data.peak_multiple)}
          />
          <Figure label="Detected" value={formatDays(data.days_since_detection)} />
          <Figure label="At detection" value={formatUsd(data.first_market_cap)} small />
        </div>
        <p className="mt-3 border-t border-line/60 pt-3 text-xs leading-relaxed text-ink-faint">
          Measured from first detection, not from launch. A project that had already run
          before the Radar noticed it starts here at 1×.
        </p>
      </Panel>

      {/* --- Achievements -------------------------------------------------- */}
      {data.achievements.length > 0 && (
        <section>
          <Label>Milestones</Label>
          <div className="mt-3 flex flex-wrap gap-2">
            {data.achievements.map((achievement) => (
              <span
                key={achievement.tier}
                title={`Reached ${achievement.tier} after ${formatDays(achievement.days_to_achieve)}`}
                className="rounded-chip border border-apex/40 bg-apex/10 px-2.5 py-1 text-xs text-apex"
              >
                <span data-numeric className="font-mono">
                  {achievement.tier}
                </span>
                <span className="ml-1.5 opacity-70">
                  {formatDays(achievement.days_to_achieve)}
                </span>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* --- Why it is on the Radar --------------------------------------- */}
      <Panel>
        <Label>Why the engine concluded this</Label>
        <div className="mt-3 flex flex-col gap-2.5">
          {data.reasons.length === 0 ? (
            <p className="text-sm text-ink-faint">
              No readout available for this token right now.
            </p>
          ) : (
            data.reasons.map((reason) => (
              <div key={reason.code} className="flex items-start gap-2.5">
                <span
                  className="mt-[7px] size-1.5 shrink-0 rounded-full"
                  style={{ background: SEVERITY_TONE[reason.severity] }}
                  aria-hidden
                />
                <p className="min-w-0 text-sm leading-relaxed text-ink-dim">
                  {reason.message}
                  <span
                    className="ml-2 text-[0.625rem] uppercase tracking-[0.1em]"
                    style={{ color: AGENTS[reason.agent as AgentId]?.hue }}
                  >
                    {AGENTS[reason.agent as AgentId]?.name}
                  </span>
                </p>
              </div>
            ))
          )}
        </div>
      </Panel>

      {/* --- Dimensions ---------------------------------------------------- */}
      <Panel>
        <Label>Opportunity dimensions</Label>
        <div className="mt-4 flex flex-col gap-3.5">
          {data.dimensions.map((dimension) => (
            <div key={dimension.id}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm text-ink-dim">{dimension.label}</span>
                {dimension.available ? (
                  <span data-numeric className="font-mono text-sm text-ink">
                    {num(dimension.score).toFixed(0)}
                    {dimension.effective_weight && (
                      <span className="ml-2 text-xs text-ink-faint">
                        ×{(num(dimension.effective_weight) * 100).toFixed(0)}%
                      </span>
                    )}
                  </span>
                ) : (
                  // Never rendered as zero: "no data source" and "scored badly"
                  // are different claims.
                  <span className="text-xs text-warn">Not available</span>
                )}
              </div>
              <Meter
                value={dimension.available ? ratio(dimension.score) : 0}
                segments={20}
                tone={dimension.available ? "var(--color-plasma)" : "var(--color-line)"}
                className="mt-1.5"
                label={`${dimension.label} score`}
              />
            </div>
          ))}
        </div>
      </Panel>

      {/* --- Score history -------------------------------------------------- */}
      <Panel>
        <Label>Score history</Label>
        <p className="mt-1 text-xs text-ink-faint">
          Written when the score moves materially, so the timeline stays readable.
        </p>
        {history.data && history.data.items.length > 0 ? (
          <ol className="mt-3 flex flex-col gap-2">
            {history.data.items.slice(0, 12).map((snapshot) => (
              <li
                key={snapshot.captured_at}
                className="flex items-center justify-between gap-3 border-b border-line/40 pb-2 text-xs last:border-0"
              >
                <time
                  data-numeric
                  dateTime={snapshot.captured_at}
                  className="font-mono text-ink-faint"
                >
                  {snapshot.captured_at.slice(0, 16).replace("T", " ")}
                </time>
                <span className="text-ink-faint">{CATEGORY_LABEL[snapshot.category]}</span>
                <span data-numeric className="font-mono text-ink-dim">
                  {num(snapshot.opportunity_score).toFixed(1)}
                  <span className="ml-1.5 text-ink-faint">
                    /{num(snapshot.confidence).toFixed(0)}%
                  </span>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-3 text-sm text-ink-faint">No score changes recorded yet.</p>
        )}
      </Panel>

      <div className="flex flex-wrap gap-4 border-t border-line/60 pt-4">
        <Link
          href="/radar"
          className="text-sm text-plasma transition-colors hover:text-ink"
        >
          ← Back to the Radar
        </Link>
        <Link
          href={`/tokens/${data.mint_address}`}
          className="text-sm text-ink-faint transition-colors hover:text-ink"
        >
          Market detail
        </Link>
      </div>
    </div>
  );
}

function Figure({
  label,
  value,
  tone = "neutral",
  small = false,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "neutral";
  small?: boolean;
}) {
  return (
    <div>
      <Label>{label}</Label>
      <p
        data-numeric
        className={cn(
          "mt-1 font-mono",
          small ? "text-lg text-ink-dim" : "text-2xl",
          !small && TONE_CLASS[tone],
        )}
      >
        {value}
      </p>
    </div>
  );
}

"use client";

import Link from "next/link";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useExitWatch } from "@/hooks/use-intelligence";
import { AGENTS, type AgentId } from "@/lib/design/agents";
import { formatMultiple, multipleTone } from "@/lib/radar";
import { num } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { ExitSeverity } from "@/types/intelligence";

/**
 * EXIT WATCH
 *
 * The other half of a detection platform. A product that only ever says "this
 * looks good" accumulates opinions it has no way to revise, and users learn
 * that the absence of a warning means nothing.
 *
 * **Never a sell signal.** The platform knows nothing about anyone's position,
 * cost basis or intent, and the disclaimer travels with the data rather than
 * being a footer someone could forget to render.
 */

const SEVERITY_TONE: Record<ExitSeverity, string> = {
  clear: "var(--color-safe)",
  watch: "var(--color-warn)",
  elevated: "var(--color-danger)",
};

const SEVERITY_LABEL: Record<ExitSeverity, string> = {
  clear: "Clear",
  watch: "Watch",
  elevated: "Elevated",
};

const TONE_CLASS = {
  positive: "text-safe",
  negative: "text-danger",
  neutral: "text-ink-faint",
} as const;

export default function ExitWatchPage() {
  const { data, isPending, isError } = useExitWatch();

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 pb-8">
      <header>
        <Label>Exit Watch</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">
          Where conviction is weakening
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-dim">
          Radar entries whose supporting evidence is deteriorating. Severity comes from how
          many <span className="text-ink">independent</span> signals agree — one metric
          falling is noise, several together is a pattern.
        </p>
      </header>

      {/* The disclaimer comes from the API and is rendered before the list, not
          after it. */}
      {data && (
        <Panel density="compact" className="border-warn/25 bg-warn/[0.04]">
          <p className="text-sm text-ink-dim">{data.disclaimer}</p>
        </Panel>
      )}

      {isError ? (
        <ErrorState
          body="Exit Watch is not responding. Assessments are computed live, so nothing is stale — this is a read failure."
          onRetry={() => window.location.reload()}
        />
      ) : isPending ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-28" />
          ))}
        </div>
      ) : data.items.length === 0 ? (
        <EmptyState
          agent="sentinel"
          title="Nothing is weakening"
          body="No Radar entry currently shows deteriorating evidence. This view fills as opportunities roll over — and they do."
        />
      ) : (
        <>
          <p className="text-xs text-ink-faint">
            {data.total} {data.total === 1 ? "entry" : "entries"} weakening
          </p>
          <div className="flex flex-col gap-3">
            {data.items.map((assessment) => {
              const tone = SEVERITY_TONE[assessment.severity];
              return (
                <Panel key={assessment.mint_address} accent={tone} density="compact">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        href={`/radar/${assessment.mint_address}`}
                        className="font-mono text-sm text-ink transition-colors hover:text-plasma"
                        data-numeric
                      >
                        {assessment.mint_address.slice(0, 6)}…
                        {assessment.mint_address.slice(-4)}
                      </Link>
                      <p className="mt-1 max-w-xl text-xs leading-relaxed text-ink-faint">
                        {assessment.summary}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span
                        data-numeric
                        className={cn(
                          "font-mono text-sm",
                          TONE_CLASS[multipleTone(assessment.current_multiple)],
                        )}
                        title="Current multiple since detection"
                      >
                        {formatMultiple(assessment.current_multiple)}
                      </span>
                      <span
                        className="rounded-chip border px-2 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.1em]"
                        style={{
                          color: tone,
                          borderColor: `color-mix(in oklch, ${tone} 35%, transparent)`,
                          background: `color-mix(in oklch, ${tone} 10%, transparent)`,
                        }}
                      >
                        {SEVERITY_LABEL[assessment.severity]}
                      </span>
                    </div>
                  </div>

                  <ul className="mt-3 flex flex-col gap-1.5 border-t border-line/60 pt-2.5">
                    {assessment.signals.map((signal) => (
                      <li key={signal.code} className="flex items-start gap-2.5">
                        <span
                          className="mt-0.5 shrink-0"
                          style={{ color: AGENTS[signal.agent as AgentId]?.hue }}
                        >
                          <AgentSigil agent={signal.agent as AgentId} size={13} />
                        </span>
                        <p className="min-w-0 text-xs leading-relaxed text-ink-dim">
                          {signal.message}
                        </p>
                      </li>
                    ))}
                  </ul>

                  {/* Coverage stated on every card: Exit Watch can never see
                      everything, and a warning that implied completeness would
                      be its own kind of dishonesty. */}
                  <p className="mt-2.5 text-[0.6875rem] text-ink-faint">
                    {num(assessment.coverage).toFixed(0)}% of declared signals could be
                    checked — wallet-level distribution is not collected.
                  </p>
                </Panel>
              );
            })}
          </div>
        </>
      )}

      <div className="flex flex-wrap gap-4 border-t border-line/60 pt-4">
        <Link
          href="/radar"
          className="text-sm text-plasma transition-colors hover:text-ink"
        >
          ← Back to the Radar
        </Link>
        <Link
          href="/hall-of-fame"
          className="text-sm text-ink-faint transition-colors hover:text-ink"
        >
          The permanent record
        </Link>
      </div>
    </div>
  );
}

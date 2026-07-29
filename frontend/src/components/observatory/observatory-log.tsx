"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Label, Panel } from "@/components/ui/panel";
import { StatusDot } from "@/components/ui/badge";
import { AGENTS } from "@/lib/design/agents";
import {
  LOG_CATEGORY_LABEL,
  type LogCategory,
  type LogEntry,
  type LogSeverity,
} from "@/hooks/use-observatory-log";
import { cn } from "@/lib/utils";

/**
 * OBSERVATORY LOG
 *
 * The station's running record. Newest at the top, timestamped in UTC because
 * a market that never closes has no local time worth showing.
 *
 * Entries arrive with a rise animation and never re-order, so the eye can
 * follow a single line as it settles. The list is capped and scrolls inside
 * itself rather than growing the page.
 */
const SEVERITY_TONE: Record<LogSeverity, string> = {
  info: "var(--color-line-bright)",
  positive: "var(--color-safe)",
  caution: "var(--color-warn)",
  critical: "var(--color-danger)",
};

const SEVERITY_LABEL: Record<LogSeverity, string> = {
  info: "Informational",
  positive: "Positive",
  caution: "Caution",
  critical: "Critical",
};

/** Categories in the order they should be offered, not alphabetical. */
const CATEGORY_ORDER: LogCategory[] = [
  "discovery",
  "ai",
  "risk",
  "market",
  "infrastructure",
];

export function ObservatoryLog({
  entries,
  live,
  className,
}: {
  entries: LogEntry[];
  live: boolean;
  className?: string;
}) {
  const [filter, setFilter] = useState<LogCategory | "all">("all");

  const counts = useMemo(() => {
    const tally = {} as Record<LogCategory, number>;
    for (const entry of entries) {
      tally[entry.category] = (tally[entry.category] ?? 0) + 1;
    }
    return tally;
  }, [entries]);

  const present = useMemo(
    () => CATEGORY_ORDER.filter((category) => (counts[category] ?? 0) > 0),
    [counts],
  );

  const visible = useMemo(
    () => (filter === "all" ? entries : entries.filter((e) => e.category === filter)),
    [entries, filter],
  );

  return (
    <Panel density="flush" className={cn("flex flex-col", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-line p-4">
        <div>
          <Label>Observatory log</Label>
          <p className="mt-1 text-sm text-ink-dim">Division activity, newest first</p>
        </div>
        <span className="flex items-center gap-1.5">
          <StatusDot
            live={live}
            tone={live ? "var(--color-safe)" : "var(--color-ink-faint)"}
          />
          <span data-numeric className="text-label uppercase text-ink-faint">
            UTC
          </span>
        </span>
      </div>

      {/* Category filter.
          Chronology is what makes a log readable, so grouping is done by
          filtering rather than by splitting the list into sections that would
          each lose the ordering. Only categories that actually have entries get
          a control — a filter that can only ever return nothing is a claim the
          station makes activity it does not. */}
      {present.length > 1 && (
        <div
          role="group"
          aria-label="Filter log by category"
          className="flex flex-wrap gap-1.5 border-b border-line px-4 py-2.5"
        >
          <FilterChip
            active={filter === "all"}
            onClick={() => setFilter("all")}
            label="All"
            count={entries.length}
          />
          {present.map((category) => (
            <FilterChip
              key={category}
              active={filter === category}
              onClick={() => setFilter(category)}
              label={LOG_CATEGORY_LABEL[category]}
              count={counts[category]}
            />
          ))}
        </div>
      )}

      <ol className="max-h-[420px] overflow-y-auto">
        {visible.length === 0 ? (
          <li className="px-4 py-10 text-center text-sm text-ink-faint">
            {entries.length === 0
              ? "Awaiting division activity. The log records only real state changes."
              : `Nothing recorded under ${LOG_CATEGORY_LABEL[filter as LogCategory]} yet.`}
          </li>
        ) : (
          visible.map((entry) => {
            const spec = AGENTS[entry.agent];
            return (
              <li
                key={entry.id}
                className="animate-[rise_0.4s_var(--ease-instrument)_both] border-b border-line/40 last:border-0"
              >
                <Link
                  href={`/tokens/${entry.mint}`}
                  className="flex gap-3 px-4 py-2.5 transition-colors hover:bg-elevated/40"
                >
                  <time
                    data-numeric
                    dateTime={entry.at.toISOString()}
                    className="shrink-0 pt-0.5 text-[0.6875rem] text-ink-faint"
                  >
                    {entry.at.toISOString().slice(11, 19)}
                  </time>

                  <span className="shrink-0 pt-0.5" style={{ color: spec.hue }}>
                    <AgentSigil agent={entry.agent} size={13} />
                  </span>

                  <span className="min-w-0 flex-1">
                    <span
                      className="text-label font-semibold uppercase"
                      style={{ color: spec.hue }}
                    >
                      {spec.name}
                    </span>
                    <span
                      className={cn(
                        "ml-2 text-xs",
                        entry.elite ? "text-apex" : "text-ink-dim",
                      )}
                    >
                      {entry.message}
                    </span>
                  </span>

                  {/* Severity as a hairline, not a badge: it has to be findable
                      when scanning for trouble without competing with the
                      agent colour that carries identity. */}
                  <span
                    className="mt-1 h-3 w-[2px] shrink-0 rounded-full"
                    style={{ background: SEVERITY_TONE[entry.severity] }}
                    title={SEVERITY_LABEL[entry.severity]}
                  >
                    <span className="sr-only">{SEVERITY_LABEL[entry.severity]}</span>
                  </span>
                </Link>
              </li>
            );
          })
        )}
      </ol>
    </Panel>
  );
}

/**
 * A real `button` with `aria-pressed`, not a styled div.
 *
 * These are toggles rather than navigation, so `aria-pressed` is what tells a
 * screen reader the current state; the visual treatment alone would leave that
 * information available only to people who can see colour.
 */
function FilterChip({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-chip border px-2 py-1 text-[0.6875rem] tracking-wide transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma",
        active
          ? "border-plasma/40 bg-plasma/12 text-plasma"
          : "border-line text-ink-faint hover:border-line-bright hover:text-ink-dim",
      )}
    >
      {label}
      <span data-numeric className="ml-1.5 opacity-60">
        {count}
      </span>
    </button>
  );
}

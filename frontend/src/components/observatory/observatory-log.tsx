"use client";

import Link from "next/link";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Label, Panel } from "@/components/ui/panel";
import { StatusDot } from "@/components/ui/badge";
import { AGENTS } from "@/lib/design/agents";
import type { LogEntry } from "@/hooks/use-observatory-log";
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
export function ObservatoryLog({
  entries,
  live,
  className,
}: {
  entries: LogEntry[];
  live: boolean;
  className?: string;
}) {
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

      <ol className="max-h-[420px] overflow-y-auto">
        {entries.length === 0 ? (
          <li className="px-4 py-10 text-center text-sm text-ink-faint">
            Awaiting division activity. The log records only real state changes.
          </li>
        ) : (
          entries.map((entry) => {
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
                </Link>
              </li>
            );
          })
        )}
      </ol>
    </Panel>
  );
}

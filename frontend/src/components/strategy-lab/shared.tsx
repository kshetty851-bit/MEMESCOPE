"use client";

import { Badge } from "@/components/ui/badge";
import { Label, Panel } from "@/components/ui/panel";
import { Tooltip } from "@/components/ui/tooltip";
import {
  FLAG_MEANING,
  pct,
  tone,
  usd,
  type LabDataset,
} from "@/lib/strategy-lab";
import { cn } from "@/lib/utils";

/**
 * The pieces every Strategy Lab section repeats.
 *
 * Three of them exist because the whole subsystem's credibility rests on them
 * being impossible to miss: the SIMULATED marker, the honesty flags, and the
 * dataset provenance. A leaderboard without its candidate count and its
 * exclusion reasons is not a research result, so `DatasetFooter` renders under
 * every board rather than on an "about" page nobody opens.
 */

export function SimulatedBadge({ className }: { className?: string }) {
  return (
    <Tooltip
      content="Simulated research capital. No paper position, no real position, and no transaction is created by anything on this page."
      side="bottom"
    >
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-sm border border-warn/40 bg-warn/10 px-2 py-0.5 text-label font-semibold uppercase tracking-wide text-warn",
          className,
        )}
      >
        Simulated capital
      </span>
    </Tooltip>
  );
}

export function FlagChips({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {flags.map((flag) => (
        <Tooltip key={flag} content={FLAG_MEANING[flag] ?? flag} side="top">
          <span className="inline-flex cursor-help items-center rounded-sm border border-warn/35 bg-warn/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-warn">
            {flag.replaceAll("_", " ")}
          </span>
        </Tooltip>
      ))}
    </span>
  );
}

/** Sample size, rendered so a thin record cannot look authoritative. */
export function SampleCount({ n, threshold }: { n: number; threshold: number }) {
  const thin = n < threshold;
  return (
    <span
      className={cn(
        "inline-flex items-baseline gap-1 font-mono tabular-nums",
        thin ? "text-warn" : "text-ink",
      )}
    >
      <span className="text-md font-semibold">{n}</span>
      {thin ? <span className="text-[10px] uppercase">thin</span> : null}
    </span>
  );
}

export function Money({
  value,
  digits = 2,
  signed = false,
}: {
  value: number | null | undefined;
  digits?: number;
  signed?: boolean;
}) {
  const t = signed ? tone(value ?? null) : "neutral";
  return (
    <span
      className={cn(
        "font-mono tabular-nums",
        t === "positive" && "text-up",
        t === "negative" && "text-down",
      )}
    >
      {usd(value, digits)}
    </span>
  );
}

export function Percent({
  value,
  digits = 1,
  signed = true,
}: {
  value: number | null | undefined;
  digits?: number;
  signed?: boolean;
}) {
  const t = signed ? tone(value ?? null) : "neutral";
  return (
    <span
      className={cn(
        "font-mono tabular-nums",
        t === "positive" && "text-up",
        t === "negative" && "text-down",
      )}
    >
      {pct(value, digits)}
    </span>
  );
}

/**
 * Provenance. Under every board, never behind a link.
 *
 * Candidate count, usable count, and a reason for every exclusion — §8's
 * requirement. A figure without these is a number, not evidence.
 */
export function DatasetFooter({ dataset }: { dataset: LabDataset | null }) {
  if (!dataset) {
    return (
      <p className="px-4 py-3 text-xs text-ink-3">
        No historical replay has been recorded yet.
      </p>
    );
  }
  const from = dataset.from ? dataset.from.slice(0, 10) : "—";
  const to = dataset.to ? dataset.to.slice(0, 10) : "—";
  return (
    <div className="space-y-2 border-t border-line px-4 py-3 text-xs text-ink-3">
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        <span>
          Dataset <span className="font-mono text-ink-2">{from} → {to}</span>
        </span>
        <span>
          Canonical opportunities{" "}
          <span className="font-mono text-ink-2">{dataset.candidates}</span>
        </span>
        <span>
          Usable <span className="font-mono text-ink-2">{dataset.usable}</span>
        </span>
        <span>
          Excluded <span className="font-mono text-ink-2">{dataset.excluded}</span>
        </span>
        <span>
          Observations{" "}
          <span className="font-mono text-ink-2">
            {dataset.observations.toLocaleString("en-US")}
          </span>
        </span>
      </div>
      {Object.keys(dataset.exclusions).length ? (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(dataset.exclusions).map(([reason, count]) => (
            <Badge key={reason} tone="neutral">
              <span className="font-mono">{count}</span>
              <span className="lowercase">{reason.replaceAll("_", " ")}</span>
            </Badge>
          ))}
        </div>
      ) : null}
      {Object.keys(dataset.venues).length ? (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(dataset.venues).map(([venue, count]) => (
            <Badge key={venue} tone="neutral">
              {venue} <span className="font-mono">{count}</span>
            </Badge>
          ))}
        </div>
      ) : null}
      <p className="text-ink-4">
        Canonical v{dataset.canonical_version} · metrics v{dataset.metrics_version}
        {dataset.finished_at
          ? ` · replayed ${dataset.finished_at.slice(0, 16).replace("T", " ")} UTC`
          : null}
      </p>
    </div>
  );
}

export function SectionNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-md border border-line bg-raised/40 px-3 py-2 text-xs leading-relaxed text-ink-3">
      {children}
    </p>
  );
}

export function StatTile({
  label,
  value,
  hint,
  tone: valueTone,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "positive" | "negative" | "neutral";
}) {
  return (
    <Panel density="compact" className="min-w-0">
      <Label>{label}</Label>
      <p
        className={cn(
          "mt-1 truncate font-mono text-lg tabular-nums",
          valueTone === "positive" && "text-up",
          valueTone === "negative" && "text-down",
          !valueTone && "text-ink",
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-0.5 truncate text-xs text-ink-3">{hint}</p> : null}
    </Panel>
  );
}

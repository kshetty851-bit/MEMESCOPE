"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Panel } from "@/components/ui/panel";
import { Why } from "@/components/decision/why";
import { CONVICTION_TONE } from "@/lib/conviction";
import {
  SCOREBOARD_WINDOWS as WINDOWS,
  type ScoreboardWindow as Window,
  offPeakPercent,
  scopeToWindow,
  summarise,
} from "@/lib/scoreboard";
import { cn } from "@/lib/utils";
import type { RadarEntry } from "@/types/radar";

/**
 * The Radar Scoreboard — LETZMOON's own record, stated plainly.
 *
 * This is the most consequential surface in the product, because it is the one
 * place the platform is judged rather than judging. Two decisions follow from
 * that, and both cost the numbers on display:
 *
 * **Peak and current are always shown together.** A detection that reached
 * 5.84× and now sits at 0.08× is not a 5.84× call, and showing only the peak
 * would be the single most flattering lie this page could tell. Both figures
 * are given equal weight and the drawdown between them is spelled out.
 *
 * **The denominator is every detection, never the good ones.** A win rate over
 * a filtered set is not a win rate. When it reads 3% because one detection in
 * thirty reached 2×, that is what it says.
 *
 * Time filters narrow the window, not the population inside it — a 24H view
 * shows every detection from the last day including the failures, never the
 * survivors of it.
 */

export function RadarScoreboard({
  entries,
  isPending,
}: {
  entries: RadarEntry[];
  isPending?: boolean;
}) {
  const [window, setWindow] = useState<Window>("all");

  const scoped = useMemo(() => scopeToWindow(entries, window, Date.now()), [entries, window]);

  const stats = useMemo(() => summarise(scoped), [scoped]);

  return (
    <Panel density="comfortable" className="flex flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-lg font-medium tracking-tight text-ink">Radar scoreboard</h2>
            <Why>
              Every detection LETZMOON has made in this window, including the
              ones that went nowhere. Returns are measured from the platform&rsquo;s
              own first detection, never from a token&rsquo;s launch — measuring
              from launch would credit moves it never called.
            </Why>
          </div>
          <p className="text-sm text-ink-dim">
            Peak and current shown together. A call that reached 5× and gave it
            back is not a 5× call.
          </p>
        </div>

        <div className="flex gap-1" role="group" aria-label="Time window">
          {WINDOWS.map((spec) => (
            <button
              key={spec.id}
              type="button"
              onClick={() => setWindow(spec.id)}
              aria-pressed={window === spec.id}
              className={cn(
                "rounded-chip px-2.5 py-1 font-mono text-xs tracking-wide transition-colors",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
                "focus-visible:outline-brand",
                window === spec.id
                  ? "bg-brand/20 text-ink"
                  : "text-ink-faint hover:bg-elevated hover:text-ink-dim",
              )}
            >
              {spec.label}
            </button>
          ))}
        </div>
      </header>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <Stat label="Tracked" value={String(stats.total)} hint="Detections in this window" />
        <Stat
          label="Reached 2×"
          value={stats.total ? `${stats.winRate}%` : "—"}
          hint={`${stats.reached2x} of ${stats.total}. Counted over every detection, not the good ones.`}
          tone={stats.reached2x > 0 ? "var(--color-brand-secondary)" : undefined}
        />
        <Stat
          label="Best peak"
          value={stats.bestPeak ? `${stats.bestPeak.toFixed(2)}×` : "—"}
          hint="The highest point any detection reached after being found."
          tone="var(--color-brand-secondary)"
        />
        <Stat
          label="Median now"
          value={stats.medianCurrent ? `${stats.medianCurrent.toFixed(2)}×` : "—"}
          hint="The middle detection's current return. Below 1.00× means the typical call is down."
          tone={
            stats.medianCurrent !== null && stats.medianCurrent < 1
              ? "var(--color-danger)"
              : undefined
          }
        />
        <Stat
          label="Above entry"
          value={stats.total ? `${stats.greenNow}%` : "—"}
          hint="Currently at or above the price at detection."
        />
        <Stat
          label="Elite"
          value={String(stats.elite)}
          hint="Detections where four independent dimensions agreed. Rare by construction."
          tone={stats.elite > 0 ? CONVICTION_TONE.very_high : undefined}
        />
      </dl>

      {isPending ? (
        <p className="py-6 text-center text-sm text-ink-faint">Reading the record…</p>
      ) : scoped.length === 0 ? (
        <p className="max-w-prose py-6 text-sm leading-relaxed text-ink-dim">
          No detections in this window. That is the record for the period, not a
          gap in it — widen the window to see the full history.
        </p>
      ) : (
        <div className="-mx-2 overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line/60 text-left">
                <Th className="w-8">#</Th>
                <Th>Project</Th>
                <Th className="text-right">Detected at</Th>
                <Th className="text-right">Peak</Th>
                <Th className="text-right">Now</Th>
                <Th className="text-right">Off peak</Th>
                <Th>Category</Th>
              </tr>
            </thead>
            <tbody>
              {[...scoped]
                .sort((a, b) => Number(b.peak_multiple ?? 0) - Number(a.peak_multiple ?? 0))
                .slice(0, 12)
                .map((entry, index) => (
                  <Row key={entry.mint_address} entry={entry} rank={index + 1} />
                ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function Row({ entry, rank }: { entry: RadarEntry; rank: number }) {
  const peak = Number(entry.peak_multiple ?? 1);
  const now = Number(entry.current_multiple ?? 1);
  const offPeak = offPeakPercent(peak, now);

  // Names, never raw mints, whenever the platform has one.
  const label = entry.symbol ?? entry.name;

  return (
    <tr className="border-b border-line/40 last:border-0 hover:bg-elevated/40">
      <Td className="font-mono text-ink-faint">{rank}</Td>
      <Td>
        <Link
          href={`/tokens/${entry.mint_address}`}
          className="font-medium text-ink hover:text-brand"
        >
          {label ?? (
            <span className="font-mono text-ink-dim">
              {entry.mint_address.slice(0, 4)}…{entry.mint_address.slice(-4)}
            </span>
          )}
        </Link>
        {entry.name && entry.symbol && entry.name !== entry.symbol ? (
          <span className="ml-2 text-xs text-ink-faint">{entry.name}</span>
        ) : null}
      </Td>
      <Td className="text-right font-mono text-ink-dim">
        {entry.first_market_cap ? formatCompact(Number(entry.first_market_cap)) : "—"}
      </Td>
      <Td className="text-right font-mono text-safe">{peak.toFixed(2)}×</Td>
      <Td
        className="text-right font-mono"
        style={{ color: now >= 1 ? "var(--color-safe)" : "var(--color-danger)" }}
      >
        {now.toFixed(2)}×
      </Td>
      <Td className="text-right font-mono text-ink-faint">
        {offPeak > 0 ? `−${offPeak}%` : "—"}
      </Td>
      <Td className="text-xs uppercase tracking-[0.08em] text-ink-faint">
        {entry.category.replace(/_/g, " ")}
      </Td>
    </tr>
  );
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-panel border border-line/50 bg-elevated/30 p-3">
      <dt className="text-[0.625rem] uppercase tracking-[0.1em] text-ink-faint">{label}</dt>
      <dd
        data-numeric
        className="font-mono text-xl tabular-nums text-ink"
        style={tone ? { color: tone } : undefined}
      >
        {value}
      </dd>
      <p className="text-[0.6875rem] leading-snug text-ink-faint">{hint}</p>
    </div>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={cn(
        "px-2 pb-2 text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-ink-faint",
        className,
      )}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  className,
  style,
}: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <td className={cn("px-2 py-2.5 tabular-nums", className)} style={style}>
      {children}
    </td>
  );
}


function formatCompact(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

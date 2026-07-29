"use client";

import Link from "next/link";
import { useState } from "react";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useHallOfFame, useHallOfLessons } from "@/hooks/use-intelligence";
import { formatUsd } from "@/lib/format";
import {
  CATEGORY_LABEL,
  formatAgo,
  formatDays,
  formatMultiple,
  multipleTone,
} from "@/lib/radar";
import { cn } from "@/lib/utils";
import type { HallEntry } from "@/types/intelligence";
import type { RadarCategory } from "@/types/radar";

/**
 * THE PERMANENT RECORD
 *
 * Two halves of one table, deliberately on one page behind one toggle rather
 * than on two pages one of which nobody links to.
 *
 * The Hall of Lessons is the more important half. A platform that publishes
 * only its winners has published nothing, and putting the failures one click —
 * not one navigation — away is the difference between disclosure and burial.
 */

type View = "fame" | "lessons";

const TONE_CLASS = {
  positive: "text-safe",
  negative: "text-danger",
  neutral: "text-ink-faint",
} as const;

export default function HallPage() {
  const [view, setView] = useState<View>("fame");

  const fame = useHallOfFame(25);
  const lessons = useHallOfLessons(25);
  const active = view === "fame" ? fame : lessons;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 pb-8">
      <header>
        <Label>The permanent record</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">
          {view === "fame"
            ? "Radar calls that became winners"
            : "Radar calls that did not work"}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-dim">
          {view === "fame"
            ? "Ranked by peak return since detection — what the call was worth at its best, not what it is worth today."
            : "Ranked by current return since detection. Nothing here is filtered or softened; these entries are counted in exactly the same denominator as the winners."}
        </p>
      </header>

      <div role="group" aria-label="Choose record" className="flex gap-1.5">
        <Toggle
          active={view === "fame"}
          onClick={() => setView("fame")}
          label="Hall of Fame"
        />
        <Toggle
          active={view === "lessons"}
          onClick={() => setView("lessons")}
          label="Hall of Lessons"
        />
      </div>

      {active.isError ? (
        <ErrorState
          body="The record is not responding. It is append-only and intact — this is a read failure."
          onRetry={() => window.location.reload()}
        />
      ) : active.isPending ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-14" />
          ))}
        </div>
      ) : active.data.length === 0 ? (
        <EmptyState
          agent="oracle"
          title="Nothing recorded yet"
          body="The Radar has not detected anything with a measurable outcome. Every detection lands here eventually — winner or not."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[52rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left">
                <Th>Token</Th>
                <Th>Detected</Th>
                <Th align="right">At detection</Th>
                <Th align="right">Peak</Th>
                <Th align="right">Now</Th>
                <Th align="right">Peak ×</Th>
                <Th align="right">Current ×</Th>
                <Th align="right">Days to peak</Th>
              </tr>
            </thead>
            <tbody>
              {active.data.map((entry) => (
                <Row key={entry.mint_address} entry={entry} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Panel density="compact">
        <Label>Why both halves exist</Label>
        <p className="mt-2 text-sm leading-relaxed text-ink-dim">
          Every project the Radar has ever detected stays on this record permanently.
          Returns are measured from{" "}
          <span className="text-ink">LETZMOON&rsquo;s first detection</span>, never from
          launch — measuring from launch would credit the platform with moves it never
          called.
        </p>
      </Panel>

      <div className="flex flex-wrap gap-4 border-t border-line/60 pt-4">
        <Link
          href="/radar"
          className="text-sm text-plasma transition-colors hover:text-ink"
        >
          ← Back to the Radar
        </Link>
        <Link
          href="/track-record"
          className="text-sm text-ink-faint transition-colors hover:text-ink"
        >
          Aggregate performance
        </Link>
      </div>
    </div>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={cn(
        "pb-2 pr-4 text-xs font-medium text-ink-faint",
        align === "right" && "text-right",
      )}
    >
      {children}
    </th>
  );
}

function Row({ entry }: { entry: HallEntry }) {
  return (
    <tr className="border-b border-line/40 last:border-0">
      <td className="py-2.5 pr-4">
        <Link
          href={`/radar/${entry.mint_address}`}
          data-numeric
          className="font-mono text-xs text-ink transition-colors hover:text-plasma"
        >
          {entry.mint_address.slice(0, 6)}…{entry.mint_address.slice(-4)}
        </Link>
        <span className="ml-2 text-[0.625rem] uppercase tracking-wide text-ink-faint">
          {CATEGORY_LABEL[entry.category as RadarCategory] ?? entry.category}
        </span>
      </td>
      <td className="py-2.5 pr-4 text-xs text-ink-faint">
        {formatAgo(entry.days_since_detection)}
      </td>
      <Money value={entry.first_market_cap} />
      <Money value={entry.peak_market_cap} />
      <Money value={entry.current_market_cap} />
      <Multiple value={entry.peak_multiple} />
      <Multiple value={entry.current_multiple} />
      <td data-numeric className="py-2.5 text-right font-mono text-xs text-ink-faint">
        {entry.days_to_peak === null ? "—" : formatDays(entry.days_to_peak)}
      </td>
    </tr>
  );
}

function Money({ value }: { value: string | null }) {
  return (
    <td data-numeric className="py-2.5 pr-4 text-right font-mono text-xs text-ink-dim">
      {formatUsd(value)}
    </td>
  );
}

function Multiple({ value }: { value: string | null }) {
  return (
    <td
      data-numeric
      className={cn(
        "py-2.5 pr-4 text-right font-mono text-xs",
        TONE_CLASS[multipleTone(value)],
      )}
    >
      {formatMultiple(value)}
    </td>
  );
}

function Toggle({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-chip border px-3 py-1.5 text-xs transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma",
        active
          ? "border-plasma/40 bg-plasma/12 text-plasma"
          : "border-line text-ink-faint hover:border-line-bright hover:text-ink-dim",
      )}
    >
      {label}
    </button>
  );
}

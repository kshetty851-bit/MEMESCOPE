"use client";

import Link from "next/link";

import { Label, Panel } from "@/components/ui/panel";
import {
  CATEGORY_LABEL,
  CATEGORY_TONE,
  formatAgo,
  formatMultiple,
  multipleTone,
} from "@/lib/radar";
import { num } from "@/lib/scores";
import { formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RadarEntry } from "@/types/radar";

/**
 * One opportunity, as the Radar reports it.
 *
 * The card leads with **what happened since detection**, not with market cap.
 * That ordering is the product argument: a $60k project up 3× since the
 * platform found it is a better story than a $2m project it never called, and
 * a card that led with size would say the opposite.
 *
 * Both multiples are always shown, including losses. A card that hid its
 * failures would make the whole track record worthless as evidence.
 */

const TONE_CLASS = {
  positive: "text-safe",
  negative: "text-danger",
  neutral: "text-ink-faint",
} as const;

export function RadarCard({ entry }: { entry: RadarEntry }) {
  const hue = CATEGORY_TONE[entry.category];
  const currentTone = multipleTone(entry.current_multiple);
  const peakTone = multipleTone(entry.peak_multiple);

  return (
    <Panel accent={hue} interactive density="compact" className="group">
      <Link href={`/radar/${entry.mint_address}`} className="flex flex-col gap-3">
        {/* --- Identity + category ---------------------------------------- */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink">
              {entry.symbol ?? entry.name ?? (
                <span data-numeric className="font-mono">
                  {entry.mint_address.slice(0, 4)}…{entry.mint_address.slice(-4)}
                </span>
              )}
            </p>
            <p className="mt-0.5 text-xs text-ink-faint">
              Found {formatAgo(entry.days_since_detection)}
            </p>
          </div>
          <span
            className="shrink-0 rounded-chip border px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.1em]"
            style={{
              color: hue,
              borderColor: `color-mix(in oklch, ${hue} 35%, transparent)`,
              background: `color-mix(in oklch, ${hue} 10%, transparent)`,
            }}
          >
            {CATEGORY_LABEL[entry.category]}
          </span>
        </div>

        {/* --- Performance since detection --------------------------------- */}
        <div className="grid grid-cols-2 gap-3 rounded-card border border-line/60 bg-surface/40 p-2.5">
          <div>
            <Label>Since found</Label>
            <p
              data-numeric
              className={cn("mt-0.5 font-mono text-lg", TONE_CLASS[currentTone])}
            >
              {formatMultiple(entry.current_multiple)}
            </p>
          </div>
          <div>
            <Label>Peak</Label>
            <p
              data-numeric
              className={cn("mt-0.5 font-mono text-lg", TONE_CLASS[peakTone])}
            >
              {formatMultiple(entry.peak_multiple)}
            </p>
          </div>
        </div>

        {/* --- Then the size, deliberately second -------------------------- */}
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <div className="flex justify-between gap-2">
            <span className="text-ink-faint">At detection</span>
            <span data-numeric className="font-mono text-ink-dim">
              {formatUsd(entry.first_market_cap)}
            </span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-ink-faint">Now</span>
            <span data-numeric className="font-mono text-ink-dim">
              {formatUsd(entry.current_market_cap)}
            </span>
          </div>
        </div>

        {/* --- Score + confidence, always together ------------------------- */}
        <div className="flex items-center justify-between border-t border-line/60 pt-2.5 text-xs">
          <span className="text-ink-faint">
            Score{" "}
            <span data-numeric className="font-mono text-ink-dim">
              {num(entry.opportunity_score).toFixed(0)}
            </span>
          </span>
          {/* Never shown without its confidence: a score read alone is read as
              more certain than the evidence behind it. */}
          <span className="text-ink-faint">
            Confidence{" "}
            <span data-numeric className="font-mono text-ink-dim">
              {num(entry.confidence).toFixed(0)}%
            </span>
          </span>
        </div>
      </Link>
    </Panel>
  );
}

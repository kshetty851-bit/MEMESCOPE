"use client";

import { cn } from "@/lib/utils";

/**
 * JOURNEY
 *
 * One token's whole life on the Radar, in a single line.
 *
 * Built strictly from stored facts: 1× is the detection, each middle step is a
 * row in `radar_achievements`, and the last two are the entry's own peak and
 * current multiples. Nothing between the stops is drawn, because nothing
 * between them was recorded — this is a sequence of measurements, not a chart.
 *
 * Peak and current always both appear, even when current is a fraction of
 * peak. That is the point of the column: a token that ran to 36× and gave it
 * back reads as exactly that, never as a 36× call.
 */

const TIER_ORDER = ["2x", "5x", "10x", "25x", "50x", "100x", "250x", "500x", "1000x"];

function multiple(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function label(value: number): string {
  return value >= 100 ? `${Math.round(value)}×` : `${value.toFixed(2)}×`;
}

interface Stop {
  text: string;
  tone: "start" | "tier" | "peak" | "up" | "down";
}

export function Journey({
  tiers,
  peakMultiple,
  currentMultiple,
}: {
  tiers: string[];
  peakMultiple: string | null;
  currentMultiple: string | null;
}) {
  const peak = multiple(peakMultiple);
  const current = multiple(currentMultiple);

  const stops: Stop[] = [{ text: "1×", tone: "start" }];

  // Achievements in ascending order — the order they were actually crossed.
  const ordered = [...tiers].sort(
    (a, b) => TIER_ORDER.indexOf(a) - TIER_ORDER.indexOf(b),
  );
  for (const tier of ordered) {
    stops.push({ text: tier.replace("x", "×"), tone: "tier" });
  }

  // The peak is only a distinct stop when it is beyond the highest tier
  // crossed; otherwise it would repeat the last badge.
  if (peak !== null) {
    const top = ordered.at(-1);
    const highest = top ? Number(top.replace("x", "")) : 1;
    if (peak > highest * 1.01) {
      stops.push({ text: `${label(peak)} peak`, tone: "peak" });
    }
  }

  if (current !== null) {
    stops.push({
      text: `${label(current)} now`,
      tone: current >= 1 ? "up" : "down",
    });
  }

  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs tabular-nums">
      {stops.map((stop, index) => (
        <span key={`${stop.text}-${index}`} className="flex items-center gap-1">
          {index > 0 ? <span className="text-ink-faint">→</span> : null}
          <span
            className={cn(
              stop.tone === "start" && "text-ink-faint",
              stop.tone === "tier" && "text-ink-dim",
              stop.tone === "peak" && "font-medium text-ink",
              stop.tone === "up" && "font-medium text-safe",
              stop.tone === "down" && "font-medium text-danger",
            )}
          >
            {stop.text}
          </span>
        </span>
      ))}
    </div>
  );
}

/**
 * Radar scoreboard arithmetic.
 *
 * Extracted from the component so the numbers the platform is judged by are
 * testable without a DOM. Every figure here is a count or a ratio over the
 * **whole** set it is given — there is no filtering to flattering subsets, and
 * a test asserts that the denominator is always the full population.
 */

import type { RadarEntry } from "@/types/radar";

export type ScoreboardWindow = "24h" | "7d" | "30d" | "all";

export const SCOREBOARD_WINDOWS: {
  id: ScoreboardWindow;
  label: string;
  hours: number | null;
}[] = [
  { id: "24h", label: "24H", hours: 24 },
  { id: "7d", label: "7D", hours: 24 * 7 },
  { id: "30d", label: "30D", hours: 24 * 30 },
  { id: "all", label: "ALL", hours: null },
];

export interface ScoreboardStats {
  total: number;
  reached2x: number;
  winRate: number;
  greenNow: number;
  bestPeak: number | null;
  medianCurrent: number | null;
  elite: number;
}

/**
 * Narrow to a time window by **detection date**.
 *
 * Deliberately not by "last evaluated": filtering on evaluation would drop
 * older detections that have gone quiet, which are exactly the ones a win rate
 * must keep counting.
 */
export function scopeToWindow(
  entries: RadarEntry[],
  window: ScoreboardWindow,
  now: number,
): RadarEntry[] {
  const spec = SCOREBOARD_WINDOWS.find((w) => w.id === window);
  if (!spec?.hours) return entries;
  const cutoff = now - spec.hours * 3_600_000;
  return entries.filter((entry) => new Date(entry.first_detected_at).getTime() >= cutoff);
}

export function summarise(entries: RadarEntry[]): ScoreboardStats {
  const total = entries.length;
  const peaks = entries.map((e) => Number(e.peak_multiple ?? 0)).filter(Number.isFinite);
  const currents = entries.map((e) => Number(e.current_multiple ?? 0)).filter(Number.isFinite);

  const reached2x = peaks.filter((p) => p >= 2).length;
  const green = currents.filter((c) => c >= 1).length;
  const sorted = [...currents].sort((a, b) => a - b);

  return {
    total,
    reached2x,
    // Over every detection, never the survivors. A win rate computed on a
    // filtered set is not a win rate.
    winRate: total ? Math.round((reached2x / total) * 100) : 0,
    greenNow: total ? Math.round((green / total) * 100) : 0,
    bestPeak: peaks.length ? Math.max(...peaks) : null,
    medianCurrent: sorted.length ? (sorted[Math.floor(sorted.length / 2)] ?? null) : null,
    elite: entries.filter((e) => e.category === "elite").length,
  };
}

/** How far a detection sits below its own peak, as a percentage. */
export function offPeakPercent(peak: number, current: number): number {
  if (!Number.isFinite(peak) || peak <= 0) return 0;
  return Math.round((1 - current / peak) * 100);
}

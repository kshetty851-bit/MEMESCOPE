import type { SeriesPoint } from "./types";

/**
 * Pure geometry for the lifecycle charts. No React, no clock.
 *
 * The invariant: **a missing value breaks the line.** `segmentsOf` splits a
 * series at every null (or non-numeric) value, so the renderer cannot
 * interpolate across a gap and cannot drop it to zero — there is simply no
 * coordinate to draw. A segment of one point is kept so an isolated reading
 * between two gaps is still visible (as a dot).
 */

export interface Pt {
  /** epoch ms */
  t: number;
  /** null = unavailable */
  v: number | null;
}

export function toPoints(series: SeriesPoint[] | undefined): Pt[] {
  if (!series) return [];
  const out: Pt[] = [];
  for (const p of series) {
    const t = Date.parse(p.t);
    if (!Number.isFinite(t)) continue;
    const raw = p.value === null || p.value === "" ? null : Number(p.value);
    out.push({ t, v: raw !== null && Number.isFinite(raw) ? raw : null });
  }
  return out.sort((a, b) => a.t - b.t);
}

export function extentOf(points: Pt[]): [number, number] | null {
  let min = Infinity;
  let max = -Infinity;
  for (const p of points) {
    if (p.v === null) continue;
    if (p.v < min) min = p.v;
    if (p.v > max) max = p.v;
  }
  return min === Infinity ? null : [min, max];
}

export type Segment = Array<[number, number]>;

export function segmentsOf(
  points: Pt[],
  x: (t: number) => number,
  y: (v: number) => number,
): Segment[] {
  const segments: Segment[] = [];
  let current: Segment = [];
  for (const p of points) {
    if (p.v === null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push([x(p.t), y(p.v)]);
    }
  }
  if (current.length) segments.push(current);
  return segments;
}

export function pathOf(segment: Segment): string {
  return segment
    .map(([px, py], i) => `${i === 0 ? "M" : "L"}${px.toFixed(2)} ${py.toFixed(2)}`)
    .join(" ");
}

/** Linear map into [lo, hi]; a flat series (max === min) sits mid-band. */
export function scaler(
  min: number,
  max: number,
  lo: number,
  hi: number,
): (v: number) => number {
  const span = max - min;
  if (span === 0) return () => (lo + hi) / 2;
  return (v) => hi - ((v - min) / span) * (hi - lo);
}

"use client";

import { useId } from "react";

import type { EquityPoint } from "./types";

/**
 * The paper book's equity over time.
 *
 * The baseline is the STARTING equity, not the series minimum: "above the
 * line" and "below the line" then mean the same thing on every window the
 * selector offers. A curve auto-scaled to its own range makes a book down 40%
 * look identical to one up 2%.
 */
export function EquityCurve({
  points,
  baseline,
  className,
}: {
  points: EquityPoint[];
  baseline: number;
  className?: string;
}) {
  const gradientId = useId();
  const values = points.map((p) => p.equity).filter(Number.isFinite);

  if (values.length < 2) {
    return (
      <div className={className} role="img" aria-label="Not enough ticks to draw a curve">
        <p className="text-label uppercase text-ink-4">Awaiting first ticks</p>
      </div>
    );
  }

  const min = Math.min(...values, baseline);
  const max = Math.max(...values, baseline);
  const range = max - min || 1;
  const W = 100;
  const H = 40;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / range) * H;
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const last = values[values.length - 1] ?? baseline;
  const rising = last >= baseline;
  const stroke = rising ? "var(--color-up)" : "var(--color-down)";

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      role="img"
      data-testid="equity-curve"
      aria-label={`Equity from $${baseline.toFixed(2)} to $${last.toFixed(2)} over ${values.length} ticks`}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <line x1="0" x2={W} y1={y(baseline)} y2={y(baseline)}
        stroke="var(--color-line)" strokeWidth="1" strokeDasharray="2 3"
        vectorEffect="non-scaling-stroke" />
      <path d={`${path} L${W},${H} L0,${H} Z`} fill={`url(#${gradientId})`} />
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.5"
        strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

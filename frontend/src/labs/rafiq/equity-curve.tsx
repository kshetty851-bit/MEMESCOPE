"use client";

import { useId } from "react";

/**
 * The equity curve: realised equity after each close, seeded at $1,000.
 *
 * A sparkline, not a chart. It carries one claim — the shape of the book over
 * its closed trades — and a labelled axis on a series of four points would
 * imply a precision the series does not have. The numbers beside it are the
 * numbers; this is the shape.
 *
 * The baseline is drawn at the starting equity rather than at the series
 * minimum, so "above the line" and "below the line" mean the same thing on
 * every strategy's card. A curve auto-scaled to its own range would make a
 * strategy down 90% look identical to one up 5%.
 */
export function EquityCurve({
  points,
  baseline,
  className,
}: {
  points: string[];
  baseline: string;
  className?: string;
}) {
  const gradientId = useId();
  const values = points.map(Number).filter(Number.isFinite);
  const base = Number(baseline);

  if (values.length < 2 || !Number.isFinite(base)) {
    return (
      <div
        className={className}
        aria-label="No closed trades yet — no curve to draw"
      >
        <p className="text-label uppercase text-ink-4">Awaiting first close</p>
      </div>
    );
  }

  const min = Math.min(...values, base);
  const max = Math.max(...values, base);
  // A flat book must not divide by zero, and must not render as a full-height
  // line either: a range of 0 is drawn as a line through the middle.
  const range = max - min || 1;
  const W = 100;
  const H = 32;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / range) * H;
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const last = values[values.length - 1] ?? base;
  const rising = last >= base;
  const stroke = rising ? "var(--color-up)" : "var(--color-down)";

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      role="img"
      aria-label={`Equity from $${base.toFixed(2)} to $${last.toFixed(2)} over ${values.length - 1} closed trades`}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <line
        x1="0"
        x2={W}
        y1={y(base)}
        y2={y(base)}
        stroke="var(--color-line)"
        strokeWidth="1"
        strokeDasharray="2 3"
        vectorEffect="non-scaling-stroke"
      />
      <path d={`${path} L${W},${H} L0,${H} Z`} fill={`url(#${gradientId})`} />
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

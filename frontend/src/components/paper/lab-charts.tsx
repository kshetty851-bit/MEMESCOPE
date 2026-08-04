"use client";

import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * LAB CHARTS
 *
 * Hand-rolled SVG, matching `ui/sparkline.tsx`: pulling in a chart library to
 * draw a line and some bars would be an admission that we do not know what we
 * are drawing.
 *
 * Every chart states what it cannot show. A chart with too few points renders
 * the reason rather than an empty frame or a straight line implying flatness —
 * "no data" and "no movement" are different claims, and only one of them is
 * usually true.
 */

function Empty({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-[120px] items-center justify-center rounded-card border border-line/60 px-4 py-6">
      <p className="text-center text-xs text-ink-faint">{label}</p>
    </div>
  );
}

export function ChartFrame({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-card border border-line bg-surface/40 p-4">
      <div>
        <p className="text-label uppercase tracking-wide text-ink-faint">{title}</p>
        {note ? <p className="mt-0.5 text-xs text-ink-faint">{note}</p> : null}
      </div>
      {children}
    </div>
  );
}

/**
 * A line over an ordered series.
 *
 * `baseline` draws the starting level so a curve that ends below where it began
 * is visibly a loss rather than just a shape.
 */
export function LineChart({
  values,
  height = 120,
  tone = "var(--color-plasma)",
  baseline,
  emptyLabel = "Not enough points to draw a line.",
}: {
  values: number[];
  height?: number;
  tone?: string;
  baseline?: number;
  emptyLabel?: string;
}) {
  const uid = useId().replace(/:/g, "");
  if (values.length < 2) return <Empty label={emptyLabel} />;

  const width = 320;
  const all = baseline === undefined ? values : [...values, baseline];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const x = (index: number) => (index / (values.length - 1)) * width;
  const y = (value: number) => height - ((value - min) / span) * (height - 8) - 4;

  const path = values.map((value, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${y(value).toFixed(2)}`).join(" ");
  const area = `${path} L${width},${height} L0,${height} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      style={{ height }}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Series of ${values.length} points, from ${values[0]?.toFixed(2)} to ${values[values.length - 1]?.toFixed(2)}`}
    >
      <defs>
        <linearGradient id={`fill-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={tone} stopOpacity="0.18" />
          <stop offset="100%" stopColor={tone} stopOpacity="0" />
        </linearGradient>
      </defs>
      {baseline !== undefined ? (
        <line
          x1="0"
          x2={width}
          y1={y(baseline)}
          y2={y(baseline)}
          stroke="var(--color-line)"
          strokeDasharray="3 4"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      ) : null}
      <path d={area} fill={`url(#fill-${uid})`} />
      <path
        d={path}
        fill="none"
        stroke={tone}
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** A histogram over pre-computed buckets. */
export function BarChart({
  bars,
  height = 120,
  emptyLabel = "No closed trades to bucket.",
}: {
  bars: { label: string; count: number; tone?: string }[];
  height?: number;
  emptyLabel?: string;
}) {
  const total = bars.reduce((sum, bar) => sum + bar.count, 0);
  if (total === 0) return <Empty label={emptyLabel} />;

  const max = Math.max(...bars.map((bar) => bar.count));

  return (
    <div className="flex flex-col gap-1.5" style={{ minHeight: height }}>
      {bars.map((bar) => (
        <div key={bar.label} className="flex items-center gap-2">
          <span className="w-20 shrink-0 truncate text-xs text-ink-faint" title={bar.label}>
            {bar.label}
          </span>
          <div className="h-3 flex-1 overflow-hidden rounded-full bg-elevated">
            <div
              className={cn("h-full rounded-full", !bar.tone && "bg-plasma/70")}
              style={{
                width: `${max > 0 ? Math.max((bar.count / max) * 100, bar.count > 0 ? 2 : 0) : 0}%`,
                background: bar.tone,
              }}
            />
          </div>
          <span className="w-8 shrink-0 text-right text-xs tabular-nums text-ink-dim">
            {bar.count}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Bucket a set of values into a fixed number of ranges.
 *
 * Pure and deterministic — the same values always produce the same buckets, so
 * a chart does not reshape itself between renders.
 */
export function bucket(
  values: number[],
  count: number,
  format: (low: number, high: number) => string,
): { label: string; count: number }[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [{ label: format(min, max), count: values.length }];

  const width = (max - min) / count;
  const buckets = Array.from({ length: count }, (_, index) => ({
    label: format(min + index * width, min + (index + 1) * width),
    count: 0,
  }));
  for (const value of values) {
    const index = Math.min(Math.floor((value - min) / width), count - 1);
    const target = buckets[index];
    if (target) target.count += 1;
  }
  return buckets;
}

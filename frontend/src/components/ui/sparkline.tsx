"use client";

import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * SPARKLINE — a trace, not a chart.
 *
 * Still hand-rolled. Pulling in a charting library to draw sixty points would
 * add ~40kB to a view that renders one of these per row, and none of them
 * would draw a 220×56 trace better than a path does.
 *
 * Three changes from the previous version:
 *
 *  - **The pulsing terminal dot is gone.** It was an `<animate>` running
 *    `indefinite`, which is fine for one instance and is sixty independently
 *    animating SVG elements once this lands in the scanner. The dot stays; it
 *    just holds still.
 *  - **Tone follows direction by default.** A trace ending below where it
 *    started reads red without the caller having to compute that — which the
 *    token page was doing inline, and no other call site was doing at all.
 *  - **It is no longer `aria-hidden` with nothing beside it.** A sparkline is
 *    real information, so it carries a text alternative describing the shape.
 *    Callers that already state the direction in an adjacent cell can pass
 *    `label={null}` to suppress it as decorative.
 */

export interface SparklineProps {
  /** Oldest → newest. Fewer than two points renders a flat rule. */
  points: number[];
  width?: number;
  height?: number;
  /**
   * Explicit stroke colour. Omit to derive from the direction of the series,
   * which is what almost every call site wants.
   */
  tone?: string;
  /** Draw the last point as a dot. */
  showTerminal?: boolean;
  /** Fill under the line. Off in dense tables, on in the dossier. */
  showArea?: boolean;
  /**
   * Text alternative. `undefined` generates one from the series; `null` marks
   * the trace decorative for callers that state the trend in text nearby.
   */
  label?: string | null;
  className?: string;
}

export function Sparkline({
  points,
  width = 120,
  height = 32,
  tone,
  showTerminal = true,
  showArea = true,
  label,
  className,
}: SparklineProps) {
  const uid = useId().replace(/:/g, "");

  const first = points[0];
  const last = points[points.length - 1];
  const direction =
    first === undefined || last === undefined
      ? "flat"
      : last > first
        ? "up"
        : last < first
          ? "down"
          : "flat";

  const stroke =
    tone ??
    (direction === "up"
      ? "var(--color-up)"
      : direction === "down"
        ? "var(--color-down)"
        : "var(--color-neutral)");

  if (points.length < 2) {
    return (
      <div
        className={cn("flex items-center justify-center", className)}
        style={{ width, height }}
        role={label === null ? undefined : "img"}
        aria-label={label === null ? undefined : "No trend data"}
        aria-hidden={label === null ? true : undefined}
      >
        <span className="h-px w-full bg-line" />
      </div>
    );
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  // A flat series would divide by zero; render it down the middle instead.
  const span = max - min || 1;
  const pad = 2;

  const coords = points.map((value, index) => {
    const x = (index / (points.length - 1)) * (width - pad * 2) + pad;
    const y = height - pad - ((value - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });

  const line = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(" ");
  const area = `${line} L${width - pad} ${height} L${pad} ${height} Z`;
  const terminal = coords[coords.length - 1]!;

  const description =
    label === undefined
      ? `Trend over ${points.length} observations, ending ${
          direction === "up" ? "higher" : direction === "down" ? "lower" : "level"
        } than it started`
      : label;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn("overflow-visible", className)}
      role={description === null ? undefined : "img"}
      aria-label={description ?? undefined}
      aria-hidden={description === null ? true : undefined}
    >
      {showArea ? (
        <>
          <defs>
            <linearGradient id={`${uid}-fill`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity="0.18" />
              <stop offset="100%" stopColor={stroke} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${uid}-fill)`} />
        </>
      ) : null}

      <path
        d={line}
        fill="none"
        stroke={stroke}
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {showTerminal ? (
        <circle cx={terminal[0]} cy={terminal[1]} r="1.75" fill={stroke} />
      ) : null}
    </svg>
  );
}

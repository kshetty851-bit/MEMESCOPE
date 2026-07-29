"use client";

import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * Sparkline.
 *
 * No chart library. A price trace at this size needs a path and a gradient;
 * pulling in 40kB of Recharts to draw sixty points would be an admission that
 * we do not know what we are drawing. Hand-rolled also means the line can carry
 * an agent hue and a lit terminal node, which no library default will give.
 */
export function Sparkline({
  points,
  width = 120,
  height = 32,
  tone = "var(--color-plasma)",
  showTerminal = true,
  className,
}: {
  points: number[];
  width?: number;
  height?: number;
  tone?: string;
  showTerminal?: boolean;
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");

  if (points.length < 2) {
    return (
      <div
        className={cn("flex items-center justify-center", className)}
        style={{ width, height }}
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
  const last = coords[coords.length - 1]!;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn("overflow-visible", className)}
      aria-hidden
    >
      <defs>
        <linearGradient id={`${uid}-fill`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={tone} stopOpacity="0.28" />
          <stop offset="100%" stopColor={tone} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${uid}-fill)`} />
      <path
        d={line}
        fill="none"
        stroke={tone}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {showTerminal && (
        <circle cx={last[0]} cy={last[1]} r="2.5" fill={tone}>
          <animate
            attributeName="opacity"
            values="1;0.35;1"
            dur="2.4s"
            repeatCount="indefinite"
          />
        </circle>
      )}
    </svg>
  );
}

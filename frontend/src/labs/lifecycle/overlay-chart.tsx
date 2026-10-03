"use client";

import { useId } from "react";

import { formatPrice, formatUsd } from "@/lib/format";

import {
  extentOf,
  pathOf,
  scaler,
  segmentsOf,
  toPoints,
  type Pt,
} from "./chart-geometry";
import { formatNumber, formatUtc, humanize } from "./display";
import type { ChartMarker, MemeSeries } from "./types";

/**
 * LIFECYCLE OVERLAY CHART — attention, price and volume on one time axis.
 *
 * Hand-built SVG, no chart library (same call as Sparkline: a handful of
 * hundred points does not justify forty kilobytes).
 *
 * WHAT IT PROMISES, AND WHY
 *
 *  - **Independent y-scales.** Attention is mentions, price is dollars, volume
 *    is dollars of a different order. Each series is scaled to its OWN min/max
 *    so the shapes can be compared in time; the legend states each range so no
 *    one reads a height as a common unit.
 *  - **Gaps are breaks.** A null value splits the path (see chart-geometry).
 *    The line is never interpolated through a gap and never dropped to zero:
 *    "we did not observe" and "it was zero" are different facts.
 *  - **Backfill is shaded and labelled.** Points before `backfill_before` were
 *    fetched about the past; the region is marked EXPLORATORY (backfill) so a
 *    reader cannot mistake it for forward-collected evidence.
 *  - **Markers carry their own glyph per kind** — not colour alone — and a
 *    <title> for hover/screen readers. They show WHEN each thing was detected,
 *    which is the whole point of the "was it early enough" question.
 *
 * Motion: nothing animates. The only transition (marker emphasis) is gated
 * behind `motion-safe`, so prefers-reduced-motion gets a static chart.
 */

const W = 720;
const H = 280;
const PAD = { left: 12, right: 12, top: 26, bottom: 28 };
const PLOT_TOP = PAD.top;
const PLOT_BOTTOM = H - PAD.bottom;

interface SeriesSpec {
  key: "attention" | "price" | "volume";
  label: string;
  stroke: string;
  dash?: string;
  format: (v: number) => string;
}

// Distinguished by colour AND dash pattern, so it survives colour-blindness.
const SERIES: SeriesSpec[] = [
  { key: "attention", label: "Attention (mentions)", stroke: "var(--color-accent)", format: (v) => formatNumber(String(v)) },
  { key: "price", label: "Price", stroke: "var(--color-score-elite)", dash: "6 3", format: (v) => formatPrice(String(v)) },
  { key: "volume", label: "Volume", stroke: "var(--color-ink-2)", dash: "2 3", format: (v) => formatUsd(String(v)) },
];

export const MARKER_LABELS: Record<string, string> = {
  token_launch: "token launch",
  attention_spike: "attention spike",
  attention_acceleration: "attention acceleration",
  revival: "revival",
  wave: "wave",
  paper_entry: "paper entry",
  paper_exit: "paper exit",
};

export function markerLabel(kind: string): string {
  return MARKER_LABELS[kind] ?? humanize(kind);
}

/** One glyph per kind, drawn around (0,0). Distinct silhouettes, not just colours. */
export function MarkerGlyph({ kind, size = 5 }: { kind: string; size?: number }) {
  const s = size;
  switch (kind) {
    case "token_launch": // triangle up
      return <path d={`M0 ${-s} L${s} ${s} L${-s} ${s} Z`} />;
    case "attention_spike": // diamond
      return <path d={`M0 ${-s} L${s} 0 L0 ${s} L${-s} 0 Z`} />;
    case "attention_acceleration": // double chevron
      return (
        <path
          d={`M${-s} ${s} L0 0 L${s} ${s} M${-s} 0 L0 ${-s} L${s} 0`}
          fill="none"
          strokeWidth="1.6"
        />
      );
    case "revival": // circle
      return <circle r={s} />;
    case "wave": // zig-zag
      return (
        <path
          d={`M${-s} ${s / 2} L${-s / 2} ${-s / 2} L0 ${s / 2} L${s / 2} ${-s / 2} L${s} ${s / 2}`}
          fill="none"
          strokeWidth="1.6"
        />
      );
    case "paper_entry": // right-pointing arrow
      return <path d={`M${-s} ${-s} L${s} 0 L${-s} ${s} Z`} />;
    case "paper_exit": // left-pointing arrow
      return <path d={`M${s} ${-s} L${-s} 0 L${s} ${s} Z`} />;
    default: // square: a kind this build has not met
      return <rect x={-s * 0.8} y={-s * 0.8} width={s * 1.6} height={s * 1.6} />;
  }
}

function markerTone(kind: string): string {
  return kind === "paper_entry" || kind === "paper_exit"
    ? "var(--color-accent)"
    : "var(--color-ink)";
}

export interface LifecycleOverlayChartProps {
  series: Pick<MemeSeries, "attention" | "price" | "volume" | "backfill_before">;
  markers: ChartMarker[];
  className?: string;
}

export function LifecycleOverlayChart({
  series,
  markers,
  className,
}: LifecycleOverlayChartProps) {
  const uid = useId().replace(/:/g, "");

  const prepared = SERIES.map((spec) => {
    const points: Pt[] = toPoints(series[spec.key]);
    return { spec, points, extent: extentOf(points) };
  });

  // The shared time axis spans every series AND every marker.
  const times: number[] = [];
  for (const { points } of prepared) for (const p of points) times.push(p.t);
  const markerTimes = markers
    .map((m) => ({ marker: m, t: Date.parse(m.t) }))
    .filter((m) => Number.isFinite(m.t));
  for (const m of markerTimes) times.push(m.t);

  if (times.length === 0) {
    return (
      <p className="rounded-md border border-line px-3 py-8 text-center text-sm text-ink-3">
        No attention, price or volume points have been collected for this meme yet.
      </p>
    );
  }

  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const tSpan = tMax - tMin || 1;
  const x = (t: number) => PAD.left + ((t - tMin) / tSpan) * (W - PAD.left - PAD.right);

  const backfillTs = series.backfill_before ? Date.parse(series.backfill_before) : NaN;
  const backfillEdge = Number.isFinite(backfillTs)
    ? Math.min(Math.max(backfillTs, tMin), tMax)
    : null;
  const showBackfill = backfillEdge !== null && backfillEdge > tMin;

  const ticks = [0, 1 / 3, 2 / 3, 1].map((f) => tMin + f * tSpan);
  const kindsPresent = Array.from(new Set(markers.map((m) => m.kind)));

  const description =
    `Attention, price and volume over time, each on its own scale. ` +
    `${markers.length} event marker${markers.length === 1 ? "" : "s"}.` +
    (showBackfill ? " Earlier part of the chart is exploratory backfill data." : "");

  return (
    <figure className={className}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={description}
        className="h-auto w-full"
        data-testid="lifecycle-overlay-chart"
      >
        <title>{description}</title>
        <defs>
          <pattern
            id={`${uid}-hatch`}
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="6" height="6" fill="var(--color-warn)" fillOpacity="0.07" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--color-warn)" strokeOpacity="0.25" strokeWidth="1" />
          </pattern>
        </defs>

        {/* plot frame */}
        <rect
          x={PAD.left}
          y={PLOT_TOP}
          width={W - PAD.left - PAD.right}
          height={PLOT_BOTTOM - PLOT_TOP}
          fill="var(--color-sunken)"
          stroke="var(--color-line)"
        />

        {/* exploratory (backfill) region */}
        {showBackfill ? (
          <g data-testid="backfill-region">
            <rect
              x={x(tMin)}
              y={PLOT_TOP}
              width={x(backfillEdge) - x(tMin)}
              height={PLOT_BOTTOM - PLOT_TOP}
              fill={`url(#${uid}-hatch)`}
            />
            <text
              x={x(tMin) + 6}
              y={PLOT_BOTTOM - 8}
              fontSize="10"
              fill="var(--color-warn)"
            >
              EXPLORATORY (backfill)
            </text>
            <line
              x1={x(backfillEdge)}
              x2={x(backfillEdge)}
              y1={PLOT_TOP}
              y2={PLOT_BOTTOM}
              stroke="var(--color-warn)"
              strokeOpacity="0.6"
              strokeDasharray="3 3"
            />
          </g>
        ) : null}

        {/* x axis */}
        {ticks.map((t, i) => (
          <g key={i}>
            <line
              x1={x(t)}
              x2={x(t)}
              y1={PLOT_BOTTOM}
              y2={PLOT_BOTTOM + 4}
              stroke="var(--color-line-strong)"
            />
            <text
              x={x(t)}
              y={H - 8}
              fontSize="10"
              fill="var(--color-ink-3)"
              textAnchor={i === 0 ? "start" : i === ticks.length - 1 ? "end" : "middle"}
            >
              {formatUtc(new Date(t).toISOString())}
            </text>
          </g>
        ))}

        {/* series: each on its own normalised scale; null breaks the line */}
        {prepared.map(({ spec, points, extent }) => {
          if (!extent) return null;
          const y = scaler(extent[0], extent[1], PLOT_TOP + 14, PLOT_BOTTOM - 14);
          const segments = segmentsOf(points, x, y);
          return (
            <g key={spec.key} data-series-group={spec.key}>
              {segments.map((segment, i) =>
                segment.length === 1 ? (
                  <circle
                    key={i}
                    data-series={spec.key}
                    data-segment="point"
                    cx={segment[0]![0]}
                    cy={segment[0]![1]}
                    r="2"
                    fill={spec.stroke}
                  />
                ) : (
                  <path
                    key={i}
                    data-series={spec.key}
                    data-segment="line"
                    d={pathOf(segment)}
                    fill="none"
                    stroke={spec.stroke}
                    strokeWidth="1.5"
                    strokeDasharray={spec.dash}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                ),
              )}
            </g>
          );
        })}

        {/* event markers */}
        {markerTimes.map(({ marker, t }, i) => {
          const px = x(t);
          const tone = markerTone(marker.kind);
          const text = `${marker.label} (${markerLabel(marker.kind)}) — ${formatUtc(marker.t)}`;
          return (
            <g
              key={`${marker.kind}-${marker.t}-${i}`}
              data-testid="chart-marker"
              data-kind={marker.kind}
              tabIndex={0}
              role="img"
              aria-label={text}
              className="outline-none motion-safe:[&_line]:transition-all [&:focus-visible_line]:stroke-[2] [&:hover_line]:stroke-[2]"
            >
              <title>{text}</title>
              <line
                x1={px}
                x2={px}
                y1={PLOT_TOP}
                y2={PLOT_BOTTOM}
                stroke={tone}
                strokeOpacity="0.55"
                strokeWidth="1"
              />
              <g transform={`translate(${px} ${PLOT_TOP - 11})`} fill={tone} stroke={tone}>
                <MarkerGlyph kind={marker.kind} />
              </g>
            </g>
          );
        })}
      </svg>

      <figcaption className="mt-3 flex flex-col gap-2 text-xs text-ink-2">
        <ul className="flex flex-wrap gap-x-5 gap-y-1" aria-label="Series legend">
          {prepared.map(({ spec, extent }) => (
            <li key={spec.key} className="flex items-center gap-2" data-testid={`legend-${spec.key}`}>
              <svg width="26" height="8" aria-hidden>
                <line
                  x1="0"
                  x2="26"
                  y1="4"
                  y2="4"
                  stroke={spec.stroke}
                  strokeWidth="2"
                  strokeDasharray={spec.dash}
                />
              </svg>
              <span>{spec.label}</span>
              <span className="text-ink-3" data-numeric>
                {extent
                  ? `scaled ${spec.format(extent[0])} – ${spec.format(extent[1])}`
                  : "unavailable — no points collected"}
              </span>
            </li>
          ))}
        </ul>
        {kindsPresent.length > 0 ? (
          <ul className="flex flex-wrap gap-x-5 gap-y-1" aria-label="Marker legend">
            {kindsPresent.map((kind) => (
              <li key={kind} className="flex items-center gap-1.5" data-testid={`legend-marker-${kind}`}>
                <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden>
                  <g fill={markerTone(kind)} stroke={markerTone(kind)}>
                    <MarkerGlyph kind={kind} />
                  </g>
                </svg>
                <span>{markerLabel(kind)}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="text-ink-3">
          Each series has its own scale, so heights are not comparable between
          lines. A break in a line is a period with no data — unavailable, not
          zero.
        </p>
      </figcaption>
    </figure>
  );
}

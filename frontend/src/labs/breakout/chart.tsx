"use client";

import { useId, useMemo } from "react";

import type { Bar, Cluster, Position, Trade } from "./types";

/**
 * Candles, resistance levels and the pre-breakout zone — in plain SVG.
 *
 * There is no charting library in this repo and this lab may not add one, so
 * this draws its own. That is not a hardship: a candle is a rectangle and a
 * wick is a line, and the three things this chart has to say — where the
 * resistance is, how close price is to it, and where we bought — are three
 * shapes, not a library.
 *
 * **The price axis is logarithmic.** A memecoin that ran from $0.0001 to
 * $0.004 over 180 days is a vertical wall on a linear axis with every earlier
 * bar squashed into the floor, and the whole point of the chart is to show
 * where price sits relative to levels formed months ago.
 */

const PAD = { top: 8, right: 58, bottom: 16, left: 6 };
const W = 720;
const H = 300;

export interface ChartProps {
  bars: Bar[];
  clusters: Cluster[];
  /** The level the PRE zone hangs under. */
  nearestResistance: number | null;
  /** How far below resistance the PRE zone reaches, in percent. */
  preZonePct: number;
  position?: Position | null;
  trades?: Trade[];
  timeframe: "day" | "hour";
}

function niceTicks(lo: number, hi: number, count = 4): number[] {
  // Log-spaced, so the labels land where the eye expects them on a log axis.
  const ticks: number[] = [];
  for (let i = 0; i <= count; i += 1) {
    ticks.push(Math.exp(Math.log(lo) + ((Math.log(hi) - Math.log(lo)) * i) / count));
  }
  return ticks;
}

function fmt(value: number): string {
  return value >= 0.01 ? value.toFixed(4) : value.toPrecision(3);
}

export function BreakoutChart({
  bars,
  clusters,
  nearestResistance,
  preZonePct,
  position = null,
  trades = [],
  timeframe,
}: ChartProps) {
  const clipId = useId();

  const geometry = useMemo(() => {
    if (bars.length === 0) return null;
    const prices = bars.flatMap((b) => [b.h, b.l]).filter((v) => v > 0);
    const marks = [
      ...clusters.map((c) => c.level),
      position?.entry,
      ...trades.flatMap((t) => [t.entry, t.exit]),
    ].filter((v): v is number => typeof v === "number" && v > 0);
    if (prices.length === 0) return null;

    // Levels are included in the range so a resistance above every bar is
    // still on screen — otherwise the one line the reader came for is the one
    // clipped off the top.
    const lo = Math.min(...prices, ...marks) * 0.97;
    const hi = Math.max(...prices, ...marks) * 1.03;
    const logLo = Math.log(lo);
    const span = Math.log(hi) - logLo || 1;

    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;
    const y = (v: number) =>
      PAD.top + plotH - ((Math.log(Math.max(v, lo)) - logLo) / span) * plotH;
    const x = (i: number) => PAD.left + (i / Math.max(bars.length, 1)) * plotW;
    const width = Math.max(plotW / Math.max(bars.length, 1) - 1, 1);
    return { lo, hi, x, y, width, plotW, plotH };
  }, [bars, clusters, position, trades]);

  if (!geometry) {
    return (
      <div
        className="flex h-[300px] items-center justify-center rounded border border-line bg-surface-2"
        role="img"
        aria-label="No candles stored for this token yet"
      >
        <p className="text-label uppercase text-ink-4">No candles yet</p>
      </div>
    );
  }

  const { lo, hi, x, y, width } = geometry;
  const preZoneTop = nearestResistance ? y(nearestResistance) : null;
  const preZoneBottom = nearestResistance
    ? y(nearestResistance * (1 - preZonePct / 100))
    : null;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      role="img"
      data-testid="breakout-chart"
      aria-label={
        `${bars.length} ${timeframe} candles` +
        (nearestResistance
          ? `, nearest resistance ${fmt(nearestResistance)}`
          : ", no resistance above")
      }
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={PAD.left} y={PAD.top} width={W - PAD.left - PAD.right}
            height={H - PAD.top - PAD.bottom} />
        </clipPath>
      </defs>

      {/* The pre-breakout zone: the band an entry is taken in. Drawn first so
          every candle and level sits on top of it. */}
      {preZoneTop !== null && preZoneBottom !== null && (
        <rect
          data-testid="pre-zone"
          x={PAD.left}
          y={preZoneTop}
          width={W - PAD.left - PAD.right}
          height={Math.max(preZoneBottom - preZoneTop, 0)}
          fill="var(--color-up)"
          opacity="0.08"
        />
      )}

      {niceTicks(lo, hi).map((value) => (
        <g key={`tick-${value}`}>
          <line x1={PAD.left} x2={W - PAD.right} y1={y(value)} y2={y(value)}
            stroke="var(--color-line)" strokeWidth="0.5" opacity="0.35" />
          <text x={W - PAD.right + 4} y={y(value) + 3}
            className="fill-ink-4 font-mono" fontSize="9">
            {fmt(value)}
          </text>
        </g>
      ))}

      <g clipPath={`url(#${clipId})`}>
        {bars.map((bar, i) => {
          const up = bar.c >= bar.o;
          const colour = up ? "var(--color-up)" : "var(--color-down)";
          const top = y(Math.max(bar.o, bar.c));
          const bottom = y(Math.min(bar.o, bar.c));
          return (
            <g key={bar.t}>
              <line x1={x(i) + width / 2} x2={x(i) + width / 2} y1={y(bar.h)}
                y2={y(bar.l)} stroke={colour} strokeWidth="0.75" opacity="0.8" />
              <rect x={x(i)} y={top} width={width}
                height={Math.max(bottom - top, 0.8)} fill={colour} opacity="0.85" />
            </g>
          );
        })}
      </g>

      {/* Resistance clusters. Unbroken solid, broken dashed — a level price
          has already closed through is history, not a wall. */}
      {clusters.map((cluster) => (
        <g key={`level-${cluster.level}`}>
          <line
            data-testid={cluster.broken ? "level-broken" : "level-unbroken"}
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(cluster.level)}
            y2={y(cluster.level)}
            stroke={cluster.broken ? "var(--color-ink-4)" : "var(--color-warn)"}
            strokeWidth={cluster.broken ? 0.75 : 1.25}
            strokeDasharray={cluster.broken ? "3 3" : undefined}
            opacity={cluster.broken ? 0.5 : 0.9}
          />
          <text x={PAD.left + 2} y={y(cluster.level) - 3}
            className="fill-ink-4 font-mono" fontSize="8">
            {`${cluster.touches}×`}
          </text>
        </g>
      ))}

      {/* Where we are in it: the entry, the live trailing stop, the exits. */}
      {position && (
        <>
          <line data-testid="entry-marker" x1={PAD.left} x2={W - PAD.right}
            y1={y(position.entry)} y2={y(position.entry)}
            stroke="var(--color-accent)" strokeWidth="1" strokeDasharray="4 2" />
          <text x={W - PAD.right + 4} y={y(position.entry) - 3}
            className="fill-accent font-mono" fontSize="8">
            entry
          </text>
          {position.qty > 0 && (
            <line data-testid="trail-marker" x1={PAD.left} x2={W - PAD.right}
              y1={y(position.trail_stop_value / position.qty)}
              y2={y(position.trail_stop_value / position.qty)}
              stroke="var(--color-down)" strokeWidth="1" strokeDasharray="2 3"
              opacity="0.8" />
          )}
        </>
      )}
      {trades.map((trade) => (
        <g key={`trade-${trade.id}`}>
          <line data-testid="exit-marker" x1={PAD.left} x2={W - PAD.right}
            y1={y(trade.exit)} y2={y(trade.exit)} stroke="var(--color-ink-3)"
            strokeWidth="0.75" strokeDasharray="1 4" opacity="0.7" />
        </g>
      ))}
    </svg>
  );
}

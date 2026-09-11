"use client";

import { useId, useMemo } from "react";

import type { Candle, Cluster, Episode } from "./types";

/**
 * Daily candles, the resistance ladder and the NEAR zone — in plain SVG.
 *
 * There is no charting library in this repo and this lab may not add one, so
 * this draws its own. That is not a hardship: a candle is a rectangle and a
 * wick is a line, and the four things this chart has to say — where the levels
 * are, which are already broken, how close price is to the nearest one, and
 * where the breakout confirmed — are four shapes, not a library.
 *
 * **The price axis is logarithmic.** These names run from ₹20 to ₹24,000 and a
 * single chart spans two and a half years; on a linear axis a stock that
 * trebled squashes its own base into the floor, and the base is where the
 * levels were formed.
 */

const PAD = { top: 8, right: 62, bottom: 16, left: 6 };
const W = 720;
const H = 300;

export interface ChartProps {
  candles: Candle[];
  clusters: Cluster[];
  /** The level the NEAR zone hangs under. */
  nearestResistance: number | null;
  /** How far below that level the NEAR band reaches, in percent. */
  nearPct: number;
  episode?: Episode | null;
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
  if (value >= 1000) return value.toFixed(0);
  return value >= 10 ? value.toFixed(1) : value.toFixed(2);
}

export function TrackerChart({
  candles,
  clusters,
  nearestResistance,
  nearPct,
  episode = null,
}: ChartProps) {
  const clipId = useId();

  const geometry = useMemo(() => {
    if (candles.length === 0) return null;
    const prices = candles.flatMap((c) => [c.h, c.l]).filter((v) => v > 0);
    if (prices.length === 0) return null;
    // Levels are inside the range so a resistance above every bar is still on
    // screen — otherwise the one line the reader came for is clipped off the
    // top, which is exactly the case where it matters most.
    const marks = [
      ...clusters.map((c) => c.level),
      episode?.ref_price,
      episode?.breakout_price,
    ].filter((v): v is number => typeof v === "number" && v > 0);

    const lo = Math.min(...prices, ...marks) * 0.97;
    const hi = Math.max(...prices, ...marks) * 1.03;
    const logLo = Math.log(lo);
    const span = Math.log(hi) - logLo || 1;
    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;
    const y = (v: number) =>
      PAD.top + plotH - ((Math.log(Math.max(v, lo)) - logLo) / span) * plotH;
    const x = (i: number) => PAD.left + (i / Math.max(candles.length, 1)) * plotW;
    const width = Math.max(plotW / Math.max(candles.length, 1) - 1, 0.8);
    return { lo, hi, x, y, width };
  }, [candles, clusters, episode]);

  if (!geometry) {
    return (
      <div
        className="flex h-[300px] items-center justify-center rounded border border-line bg-surface-2"
        role="img"
        aria-label="No daily bars stored for this stock yet"
      >
        <p className="text-label uppercase text-ink-4">No bars yet</p>
      </div>
    );
  }

  const { lo, hi, x, y, width } = geometry;
  const zoneTop = nearestResistance === null ? null : y(nearestResistance);
  const zoneBottom =
    nearestResistance === null ? null : y(nearestResistance * (1 - nearPct / 100));
  const breakoutIndex = episode?.breakout_date
    ? candles.findIndex((c) => c.d === episode.breakout_date)
    : -1;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      role="img"
      data-testid="tracker-chart"
      aria-label={
        `${candles.length} daily bars` +
        (nearestResistance !== null
          ? `, nearest resistance ${fmt(nearestResistance)}`
          : ", no unbroken resistance above")
      }
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={PAD.left} y={PAD.top} width={W - PAD.left - PAD.right}
            height={H - PAD.top - PAD.bottom} />
        </clipPath>
      </defs>

      {/* The NEAR band: within `nearPct` of the level is the state the board
          calls NEAR. Drawn first so every candle and level sits on top. */}
      {zoneTop !== null && zoneBottom !== null && (
        <rect
          data-testid="near-zone"
          x={PAD.left}
          y={zoneTop}
          width={W - PAD.left - PAD.right}
          height={Math.max(zoneBottom - zoneTop, 0)}
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
        {candles.map((candle, i) => {
          const up = candle.c >= candle.o;
          const colour = up ? "var(--color-up)" : "var(--color-down)";
          const top = y(Math.max(candle.o, candle.c));
          const bottom = y(Math.min(candle.o, candle.c));
          return (
            <g key={candle.d}>
              <line x1={x(i) + width / 2} x2={x(i) + width / 2} y1={y(candle.h)}
                y2={y(candle.l)} stroke={colour} strokeWidth="0.75" opacity="0.8" />
              <rect x={x(i)} y={top} width={width}
                height={Math.max(bottom - top, 0.8)} fill={colour} opacity="0.85" />
              {/* A bar across a corporate action. The price is unadjusted and
                  known to be wrong relative to its neighbours, so it is marked
                  rather than quietly drawn as if it were comparable. */}
              {candle.suspect && (
                <rect data-testid="suspect-bar" x={x(i)} y={PAD.top} width={width}
                  height={H - PAD.top - PAD.bottom} fill="var(--color-warn)"
                  opacity="0.14" />
              )}
            </g>
          );
        })}
      </g>

      {/* The ladder. Unbroken solid, broken dashed — a level price has already
          closed through is history, not a wall. */}
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

      {/* Where the setup was marked, and where it confirmed. */}
      {episode?.ref_price ? (
        <line data-testid="ref-marker" x1={PAD.left} x2={W - PAD.right}
          y1={y(episode.ref_price)} y2={y(episode.ref_price)}
          stroke="var(--color-accent)" strokeWidth="1" strokeDasharray="4 2"
          opacity="0.8" />
      ) : null}
      {episode?.breakout_price && breakoutIndex >= 0 ? (
        <g data-testid="breakout-marker">
          <line x1={x(breakoutIndex)} x2={x(breakoutIndex)} y1={PAD.top}
            y2={H - PAD.bottom} stroke="var(--color-accent)" strokeWidth="1"
            opacity="0.55" />
          <text x={x(breakoutIndex) + 3} y={PAD.top + 9}
            className="fill-accent font-mono" fontSize="8">
            break
          </text>
        </g>
      ) : null}
    </svg>
  );
}

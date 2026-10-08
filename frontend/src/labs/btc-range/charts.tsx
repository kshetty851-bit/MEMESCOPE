"use client";

import { useId } from "react";

import { toNumber, usd, when } from "./format";
import type { CandleOut, EquityPointOut, SignalOut } from "./types";

/**
 * HAND-ROLLED SVG, for the reason the sparkline is: two drawings on one page
 * do not justify a charting dependency. Both scale by `viewBox`, so the width
 * is the container's and the aspect ratio is fixed.
 *
 * Text is deliberately NOT drawn inside the SVG. At phone width a 900-unit
 * viewBox shrinks to about 0.4x and any in-chart label becomes unreadable, so
 * the levels are listed in HTML beneath the drawing, where they stay legible
 * and are available to a screen reader.
 */

const W = 900;
const H = 300;
const PAD_Y = 12;

interface Level {
  key: string;
  label: string;
  value: string;
  color: string;
  dashed?: boolean;
}

/**
 * `entryZone` is the fraction of the range's width the long zone (from
 * support) and the short zone (from resistance) each cover. It comes from the
 * config, not the status payload, which does not carry it; with no config the
 * zones are simply not drawn rather than guessed.
 */
export function RangeChart({
  candles,
  signal,
  entryZone,
}: {
  candles: CandleOut[];
  signal: SignalOut | null;
  entryZone?: string | null;
}) {
  const range = signal?.range ?? null;
  const support = toNumber(range?.support);
  const resistance = toNumber(range?.resistance);
  const call = signal?.call ?? "wait";
  const active = call !== "wait";
  const entry = active ? toNumber(signal?.entry) : null;
  const tp = active ? toNumber(signal?.take_profit) : null;
  const sl = active ? toNumber(signal?.stop_loss) : null;
  const zoneFraction = toNumber(entryZone);

  const parsed = candles
    .map((c) => ({
      t: c.t,
      o: toNumber(c.o),
      h: toNumber(c.h),
      l: toNumber(c.l),
      c: toNumber(c.c),
    }))
    .filter(
      (c): c is { t: string; o: number; h: number; l: number; c: number } =>
        c.o !== null && c.h !== null && c.l !== null && c.c !== null,
    );

  if (parsed.length < 2) {
    return (
      <p className="py-10 text-center text-sm text-ink-3" data-testid="range-chart-empty">
        Not enough stored candles to draw the range.
      </p>
    );
  }

  const values = [
    ...parsed.flatMap((c) => [c.h, c.l]),
    ...[support, resistance, entry, tp, sl].filter((v): v is number => v !== null),
  ];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const min = lo - span * 0.04;
  const max = hi + span * 0.04;
  const y = (v: number) => PAD_Y + ((max - v) / (max - min)) * (H - PAD_Y * 2);

  const step = W / parsed.length;
  const bodyW = Math.max(1, step * 0.6);
  const x = (i: number) => i * step + step / 2;

  const bandTop = resistance !== null ? y(resistance) : null;
  const bandBottom = support !== null ? y(support) : null;

  const zones: Array<{ key: string; from: number; to: number; color: string }> = [];
  if (
    support !== null &&
    resistance !== null &&
    zoneFraction !== null &&
    zoneFraction > 0 &&
    zoneFraction < 0.5
  ) {
    const width = resistance - support;
    zones.push(
      {
        key: "long-zone",
        from: support,
        to: support + width * zoneFraction,
        color: "var(--color-up)",
      },
      {
        key: "short-zone",
        from: resistance - width * zoneFraction,
        to: resistance,
        color: "var(--color-down)",
      },
    );
  }

  const levels: Level[] = [];
  if (resistance !== null)
    levels.push({
      key: "resistance",
      label: "Resistance",
      value: signal!.range!.resistance,
      color: "var(--color-ink-3)",
    });
  if (support !== null)
    levels.push({
      key: "support",
      label: "Support",
      value: signal!.range!.support,
      color: "var(--color-ink-3)",
    });
  if (entry !== null)
    levels.push({
      key: "entry",
      label: "Entry",
      value: signal!.entry!,
      color: "var(--color-accent)",
    });
  if (tp !== null)
    levels.push({
      key: "tp",
      label: "TP",
      value: signal!.take_profit!,
      color: "var(--color-up)",
      dashed: true,
    });
  if (sl !== null)
    levels.push({
      key: "sl",
      label: "SL",
      value: signal!.stop_loss!,
      color: "var(--color-down)",
      dashed: true,
    });

  const label =
    `BTC/USDT, last ${parsed.length} closed candles` +
    (support !== null && resistance !== null
      ? `, support ${usd(range!.support)}, resistance ${usd(range!.resistance)}`
      : ", no range detected") +
    (active
      ? `. Paper call ${call.toUpperCase()}, entry ${usd(signal!.entry)}, take profit ${usd(signal!.take_profit)}, stop loss ${usd(signal!.stop_loss)}.`
      : ". Paper call WAIT: no entry, take profit or stop loss.");

  const lineY = (v: number) => y(v).toFixed(2);

  return (
    <figure className="flex flex-col gap-2" data-testid="range-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={label}
        preserveAspectRatio="xMidYMid meet"
      >
        {bandTop !== null && bandBottom !== null ? (
          <rect
            data-testid="range-band"
            x={0}
            y={bandTop}
            width={W}
            height={Math.max(0, bandBottom - bandTop)}
            fill="var(--color-accent)"
            fillOpacity={0.07}
          />
        ) : null}

        {zones.map((zone) => (
          <rect
            key={zone.key}
            data-testid={zone.key}
            x={0}
            y={y(zone.to)}
            width={W}
            height={Math.max(0, y(zone.from) - y(zone.to))}
            fill={zone.color}
            fillOpacity={0.12}
          />
        ))}

        {support !== null ? (
          <line
            x1={0}
            x2={W}
            y1={lineY(support)}
            y2={lineY(support)}
            stroke="var(--color-ink-3)"
            strokeWidth={1}
          />
        ) : null}
        {resistance !== null ? (
          <line
            x1={0}
            x2={W}
            y1={lineY(resistance)}
            y2={lineY(resistance)}
            stroke="var(--color-ink-3)"
            strokeWidth={1}
          />
        ) : null}

        {parsed.map((c, i) => {
          const up = c.c >= c.o;
          const color = up ? "var(--color-up)" : "var(--color-down)";
          const top = y(Math.max(c.o, c.c));
          const bottom = y(Math.min(c.o, c.c));
          return (
            <g key={c.t}>
              <line
                x1={x(i)}
                x2={x(i)}
                y1={y(c.h)}
                y2={y(c.l)}
                stroke={color}
                strokeWidth={1}
              />
              <rect
                x={x(i) - bodyW / 2}
                y={top}
                width={bodyW}
                height={Math.max(1, bottom - top)}
                fill={color}
              />
            </g>
          );
        })}

        {entry !== null ? (
          <line
            data-testid="line-entry"
            x1={0}
            x2={W}
            y1={lineY(entry)}
            y2={lineY(entry)}
            stroke="var(--color-accent)"
            strokeWidth={1.5}
          />
        ) : null}
        {tp !== null ? (
          <line
            data-testid="line-tp"
            x1={0}
            x2={W}
            y1={lineY(tp)}
            y2={lineY(tp)}
            stroke="var(--color-up)"
            strokeWidth={1.5}
            strokeDasharray="6 4"
          />
        ) : null}
        {sl !== null ? (
          <line
            data-testid="line-sl"
            x1={0}
            x2={W}
            y1={lineY(sl)}
            y2={lineY(sl)}
            stroke="var(--color-down)"
            strokeWidth={1.5}
            strokeDasharray="6 4"
          />
        ) : null}
      </svg>

      <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
        <span>
          {when(parsed[0]!.t)} to {when(parsed[parsed.length - 1]!.t)} · {parsed.length}{" "}
          candles
        </span>
        {levels.map((level) => (
          <span key={level.key} className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-0 w-4 border-t-2"
              style={{
                borderColor: level.color,
                borderStyle: level.dashed ? "dashed" : "solid",
              }}
            />
            {level.label}{" "}
            <span data-numeric className="text-ink-2">
              {usd(level.value)}
            </span>
          </span>
        ))}
        {zones.length > 0 ? (
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-2.5 rounded-sm bg-up/30" />
            <span aria-hidden className="inline-block size-2.5 rounded-sm bg-down/30" />
            Entry zones
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}

const EW = 600;
const EH = 160;

/** Equity over time. A dashed rule marks where the curve started. */
export function EquityCurve({ points }: { points: EquityPointOut[] }) {
  const uid = useId().replace(/:/g, "");
  const parsed = points
    .map((p) => ({ at: p.at, v: toNumber(p.equity) }))
    .filter((p): p is { at: string; v: number } => p.v !== null);

  if (parsed.length < 2) {
    return (
      <p className="py-8 text-center text-sm text-ink-3" data-testid="equity-empty">
        Not enough closed paper trades to draw an equity curve.
      </p>
    );
  }

  const values = parsed.map((p) => p.v);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pad = 6;
  const x = (i: number) => (i / (parsed.length - 1)) * EW;
  const y = (v: number) => pad + ((hi - v) / span) * (EH - pad * 2);

  const first = parsed[0]!;
  const last = parsed[parsed.length - 1]!;
  const stroke =
    last.v > first.v
      ? "var(--color-up)"
      : last.v < first.v
        ? "var(--color-down)"
        : "var(--color-neutral)";
  const line = parsed
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)} ${y(p.v).toFixed(2)}`)
    .join(" ");
  const area = `${line} L${EW} ${EH} L0 ${EH} Z`;

  return (
    <figure className="flex flex-col gap-2" data-testid="equity-curve">
      <svg
        viewBox={`0 0 ${EW} ${EH}`}
        className="h-auto w-full"
        role="img"
        aria-label={`Paper equity from ${usd(first.v)} to ${usd(last.v)} over ${parsed.length} points, low ${usd(lo)}, high ${usd(hi)}`}
      >
        <defs>
          <linearGradient id={`${uid}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.18" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        <line
          x1={0}
          x2={EW}
          y1={y(first.v)}
          y2={y(first.v)}
          stroke="var(--color-line-strong)"
          strokeDasharray="4 4"
        />
        <path d={area} fill={`url(#${uid}-fill)`} />
        <path
          d={line}
          fill="none"
          stroke={stroke}
          strokeWidth={1.75}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
        <span>
          {when(first.at)} to {when(last.at)}
        </span>
        <span>
          Start{" "}
          <span data-numeric className="text-ink-2">
            {usd(first.v)}
          </span>
        </span>
        <span>
          Low{" "}
          <span data-numeric className="text-ink-2">
            {usd(lo)}
          </span>
        </span>
        <span>
          High{" "}
          <span data-numeric className="text-ink-2">
            {usd(hi)}
          </span>
        </span>
        <span>
          End{" "}
          <span data-numeric className="text-ink-2">
            {usd(last.v)}
          </span>
        </span>
      </figcaption>
    </figure>
  );
}

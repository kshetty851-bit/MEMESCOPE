"use client";

import { useId, useState, type KeyboardEvent, type MouseEvent } from "react";

import { cn } from "@/lib/utils";

import { monthLabel, pct, toNumber, usd, utc } from "./format";
import type { DrawdownPointOut, EquityPointOut, MonthReturn } from "./types";

/**
 * HAND-ROLLED SVG, for the reason the BTC lab's charts are: three drawings do
 * not justify a charting dependency. All scale by `viewBox`.
 *
 * Text is NOT drawn inside the SVG (it shrinks to unreadable at phone width).
 * The hovered point is read out in HTML above the drawing, where a screen
 * reader can reach it too. Nothing is computed here beyond screen coordinates:
 * every figure displayed is a value the API sent.
 */

const W = 900;
const H = 240;
const PAD = 8;

/** Index of the point nearest a pointer, from its horizontal fraction. */
function nearest(xs: number[], frac: number): number {
  const target = frac * W;
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < xs.length; i++) {
    const d = Math.abs(xs[i]! - target);
    if (d < bestDist) {
      best = i;
      bestDist = d;
    }
  }
  return best;
}

function useScrub(xs: number[]) {
  const [hover, setHover] = useState<number | null>(null);
  const n = xs.length;
  return {
    hover,
    props: {
      tabIndex: 0,
      onMouseMove: (e: MouseEvent<SVGSVGElement>) => {
        const rect = e.currentTarget.getBoundingClientRect();
        if (rect.width <= 0) return;
        setHover(nearest(xs, (e.clientX - rect.left) / rect.width));
      },
      onMouseLeave: () => setHover(null),
      onBlur: () => setHover(null),
      onKeyDown: (e: KeyboardEvent<SVGSVGElement>) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        setHover((h) => {
          const from = h ?? (e.key === "ArrowRight" ? -1 : n);
          return Math.min(n - 1, Math.max(0, from + (e.key === "ArrowRight" ? 1 : -1)));
        });
      },
    },
  };
}

function Empty({ testId, children }: { testId: string; children: string }) {
  return (
    <p className="py-8 text-center text-sm text-ink-3" data-testid={testId}>
      {children}
    </p>
  );
}

interface Pt {
  t: number;
  iso: string;
  equity: number;
  balance: string;
}

/** Equity over time. Hover (or arrow keys) reads out the date and equity. */
export function EquityChart({
  points,
  startingBalance,
}: {
  points: EquityPointOut[];
  startingBalance?: string | null;
}) {
  const uid = useId().replace(/:/g, "");
  const parsed: Pt[] = points
    .map((p) => ({
      t: new Date(p.t).getTime(),
      iso: p.t,
      equity: toNumber(p.equity),
      balance: p.balance,
    }))
    .filter((p): p is Pt => p.equity !== null && Number.isFinite(p.t));

  const t0 = parsed[0]?.t ?? 0;
  const span = (parsed[parsed.length - 1]?.t ?? 0) - t0 || 1;
  const xs = parsed.map((p) => ((p.t - t0) / span) * W);
  const { hover, props } = useScrub(xs);

  if (parsed.length < 2) {
    return <Empty testId="equity-empty">Not enough points to draw an equity curve.</Empty>;
  }

  const start = toNumber(startingBalance);
  const values = [...parsed.map((p) => p.equity), ...(start !== null ? [start] : [])];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const range = hi - lo || 1;
  const y = (v: number) => PAD + ((hi - v) / range) * (H - PAD * 2);

  const first = parsed[0]!;
  const last = parsed[parsed.length - 1]!;
  const stroke =
    last.equity > first.equity
      ? "var(--color-up)"
      : last.equity < first.equity
        ? "var(--color-down)"
        : "var(--color-neutral)";
  const line = parsed
    .map((p, i) => `${i === 0 ? "M" : "L"}${xs[i]!.toFixed(1)} ${y(p.equity).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${W} ${H} L0 ${H} Z`;
  const shown = hover ?? parsed.length - 1;
  const at = parsed[shown]!;

  return (
    <figure className="flex flex-col gap-2" data-testid="equity-chart">
      <div
        className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3"
        data-testid="equity-readout"
        aria-live="polite"
      >
        <span>{utc(at.iso)}</span>
        <span>
          Equity{" "}
          <span data-numeric className="text-ink">
            {usd(at.equity)}
          </span>
        </span>
        <span>
          Balance{" "}
          <span data-numeric className="text-ink-2">
            {usd(at.balance)}
          </span>
        </span>
        {hover === null ? (
          <span className="text-ink-4">Hover the curve to read a point</span>
        ) : null}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full cursor-crosshair"
        role="img"
        aria-label={`Equity from ${usd(first.equity)} to ${usd(last.equity)} across ${parsed.length} points, low ${usd(lo)}, high ${usd(hi)}`}
        data-testid="equity-svg"
        {...props}
      >
        <defs>
          <linearGradient id={`${uid}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.18" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        {start !== null ? (
          <line
            x1={0}
            x2={W}
            y1={y(start)}
            y2={y(start)}
            stroke="var(--color-line-strong)"
            strokeDasharray="4 4"
          />
        ) : null}
        <path d={area} fill={`url(#${uid}-fill)`} />
        <path
          d={line}
          fill="none"
          stroke={stroke}
          strokeWidth={1.75}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        {hover !== null ? (
          <g data-testid="equity-cursor">
            <line
              x1={xs[hover]}
              x2={xs[hover]}
              y1={0}
              y2={H}
              stroke="var(--color-ink-3)"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
            <circle cx={xs[hover]} cy={y(at.equity)} r={4} fill={stroke} />
          </g>
        ) : null}
      </svg>
      <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
        <span>
          {utc(first.iso)} to {utc(last.iso)}
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
        {start !== null ? <span>Dashed rule: starting balance</span> : null}
      </figcaption>
    </figure>
  );
}

/**
 * Drawdown from the running peak, drawn downward from a zero line. The API's
 * sign convention is not pinned (a depth may arrive as -4.2 or 4.2), so depth
 * is drawn as the magnitude and the readout prints the value as sent.
 */
export function DrawdownChart({
  points,
  maxDrawdownPct,
}: {
  points: DrawdownPointOut[];
  maxDrawdownPct?: number | null;
}) {
  const parsed = points
    .map((p) => ({ t: new Date(p.t).getTime(), iso: p.t, dd: toNumber(p.dd_pct) }))
    .filter(
      (p): p is { t: number; iso: string; dd: number } =>
        p.dd !== null && Number.isFinite(p.t),
    );
  const t0 = parsed[0]?.t ?? 0;
  const span = (parsed[parsed.length - 1]?.t ?? 0) - t0 || 1;
  const xs = parsed.map((p) => ((p.t - t0) / span) * W);
  const { hover, props } = useScrub(xs);

  if (parsed.length < 2) {
    return <Empty testId="drawdown-empty">Not enough points to draw a drawdown.</Empty>;
  }

  const depth = Math.max(...parsed.map((p) => Math.abs(p.dd))) || 1;
  const y = (v: number) => PAD + (Math.abs(v) / depth) * (H - PAD * 2);
  const line = parsed
    .map((p, i) => `${i === 0 ? "M" : "L"}${xs[i]!.toFixed(1)} ${y(p.dd).toFixed(1)}`)
    .join(" ");
  const area = `M0 ${PAD} ${line.replace(/^M/, "L")} L${W} ${PAD} Z`;
  const shown = hover ?? null;
  const at = shown !== null ? parsed[shown]! : null;

  return (
    <figure className="flex flex-col gap-2" data-testid="drawdown-chart">
      <div
        className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3"
        data-testid="drawdown-readout"
        aria-live="polite"
      >
        {at ? (
          <>
            <span>{utc(at.iso)}</span>
            <span>
              Drawdown{" "}
              <span data-numeric className="text-down">
                {pct(at.dd)}
              </span>
            </span>
          </>
        ) : (
          <span>Hover the chart to read a point</span>
        )}
        {maxDrawdownPct !== undefined ? (
          <span>
            Maximum{" "}
            <span data-numeric className="text-ink-2">
              {pct(maxDrawdownPct)}
            </span>
          </span>
        ) : null}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full cursor-crosshair"
        role="img"
        aria-label={`Drawdown from the running peak across ${parsed.length} points${
          maxDrawdownPct !== undefined && maxDrawdownPct !== null
            ? `, maximum ${pct(maxDrawdownPct)}`
            : ""
        }`}
        {...props}
      >
        <path d={area} fill="var(--color-down)" fillOpacity={0.16} />
        <path
          d={line}
          fill="none"
          stroke="var(--color-down)"
          strokeWidth={1.5}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        <line x1={0} x2={W} y1={PAD} y2={PAD} stroke="var(--color-line-strong)" />
        {hover !== null ? (
          <line
            x1={xs[hover]}
            x2={xs[hover]}
            y1={0}
            y2={H}
            stroke="var(--color-ink-3)"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>
    </figure>
  );
}

/** Monthly returns about a zero line. A losing month is drawn below it, in red. */
export function MonthlyBars({ months }: { months: MonthReturn[] }) {
  const rows = months
    .map((m) => ({ ...m, v: toNumber(m.return_pct) }))
    .filter((m): m is MonthReturn & { v: number } => m.v !== null);
  const n = rows.length;
  const step = n > 0 ? W / n : W;
  const xs = rows.map((_, i) => i * step + step / 2);
  const { hover, props } = useScrub(xs);

  if (n === 0)
    return <Empty testId="monthly-empty">No completed months in this window.</Empty>;

  const hi = Math.max(0, ...rows.map((m) => m.v));
  const lo = Math.min(0, ...rows.map((m) => m.v));
  const range = hi - lo || 1;
  const y = (v: number) => PAD + ((hi - v) / range) * (H - PAD * 2);
  const zero = y(0);
  const barW = Math.max(2, step * 0.66);
  const at = hover !== null ? rows[hover]! : null;

  return (
    <figure className="flex flex-col gap-2" data-testid="monthly-bars">
      <div
        className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3"
        aria-live="polite"
        data-testid="monthly-readout"
      >
        {at ? (
          <>
            <span>{monthLabel(at.month)}</span>
            <span
              data-numeric
              className={at.v < 0 ? "text-down" : at.v > 0 ? "text-up" : "text-ink-2"}
            >
              {pct(at.v, { signed: true })}
            </span>
            {at.pnl !== undefined && at.pnl !== null ? (
              <span>{usd(at.pnl, { signed: true })}</span>
            ) : null}
            {typeof at.trades === "number" ? <span>{at.trades} trades</span> : null}
          </>
        ) : (
          <span>Hover a bar to read a month</span>
        )}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={`Monthly returns for ${n} months`}
        {...props}
      >
        <line x1={0} x2={W} y1={zero} y2={zero} stroke="var(--color-line-strong)" />
        {rows.map((m, i) => {
          const top = Math.min(y(m.v), zero);
          const height = Math.max(1, Math.abs(y(m.v) - zero));
          return (
            <rect
              key={m.month}
              data-testid="month-bar"
              data-negative={m.v < 0 ? "true" : "false"}
              x={xs[i]! - barW / 2}
              y={top}
              width={barW}
              height={height}
              fill={m.v < 0 ? "var(--color-down)" : "var(--color-up)"}
              opacity={hover === null || hover === i ? 1 : 0.55}
            />
          );
        })}
      </svg>
      <ul className="flex flex-wrap gap-1.5 text-xs" aria-label="Monthly returns">
        {rows.map((m) => (
          <li
            key={m.month}
            className={cn(
              "rounded-sm border border-line px-1.5 py-0.5 tabular-nums",
              m.v < 0 ? "text-down" : m.v > 0 ? "text-up" : "text-ink-2",
            )}
          >
            <span className="text-ink-3">{monthLabel(m.month)}</span>{" "}
            {pct(m.v, { signed: true })}
          </li>
        ))}
      </ul>
    </figure>
  );
}

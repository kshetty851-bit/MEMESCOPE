"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";

/**
 * SOL/USD IN THE NAVIGATION RAIL.
 *
 * Mounted beside the nav, so it is on screen whatever the user is looking at.
 * Three decisions the code will not explain on its own:
 *
 *  - **The sparkline is the last hour of minute closes, drawn to its own
 *    range, not to zero.** SOL moves fractions of a percent in an hour; a
 *    chart anchored at zero would render sixty identical pixels. The range is
 *    the hour's own high and low, so the line shows what actually happened.
 *  - **The price flashes on change, the line does not animate.** A path that
 *    tweens between two states is reading a number that was never true. The
 *    flash marks that a new value arrived; the line is redrawn as a fact.
 *  - **Collapsed, it becomes the price alone.** A 3.5rem rail cannot hold a
 *    chart, and a squeezed one would be decoration.
 */

interface SolPrice {
  price_usd: number;
  change_pct_1h: number | null;
  change_pct_24h: number | null;
  series: number[];
  age_seconds: number;
  stale: boolean;
}

function Sparkline({ points, up }: { points: number[]; up: boolean }) {
  if (points.length < 2) return null;
  const w = 168;
  const h = 34;
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  // A flat hour would divide by zero and a one-pixel range would look like
  // noise, so the span has a floor.
  const span = Math.max(hi - lo, hi * 0.0005);
  const x = (i: number) => (i / (points.length - 1)) * w;
  const y = (p: number) => h - ((p - lo) / span) * (h - 4) - 2;
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const area = `0,${h} ${line} ${w},${h}`;
  const stroke = up ? "var(--color-up)" : "var(--color-down)";
  const last = points[points.length - 1] ?? 0;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="h-[34px] w-full overflow-visible"
      role="img"
      aria-label={`SOL, last hour: low ${lo.toFixed(2)}, high ${hi.toFixed(2)}`}
    >
      <defs>
        <linearGradient id="sol-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill="url(#sol-fill)" />
      <polyline
        points={line}
        fill="none"
        stroke={stroke}
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={w} cy={y(last)} r="2" fill={stroke} className="sol-pulse" />
    </svg>
  );
}

export function SolTicker({ collapsed }: { collapsed: boolean }) {
  const { data } = useQuery({
    queryKey: ["market", "sol"],
    queryFn: () => api.get<SolPrice>("/market/sol"),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const previous = useRef<number | null>(null);

  useEffect(() => {
    if (data?.price_usd === undefined) return;
    const before = previous.current;
    previous.current = data.price_usd;
    if (before === null || before === data.price_usd) return;
    setFlash(data.price_usd > before ? "up" : "down");
    const id = setTimeout(() => setFlash(null), 700);
    return () => clearTimeout(id);
  }, [data?.price_usd]);

  if (!data) return null;
  const change = data.change_pct_1h ?? data.change_pct_24h ?? 0;
  const up = change >= 0;

  if (collapsed) {
    return (
      <div
        className="flex flex-col items-center gap-0.5 border-t border-line-subtle py-2"
        title={`SOL $${data.price_usd.toFixed(2)}`}
      >
        <span className="text-[9px] uppercase tracking-[0.1em] text-ink-3">SOL</span>
        <span
          className={cn(
            "font-mono text-[10px] tabular-nums transition-colors duration-500",
            flash === "up" && "text-up",
            flash === "down" && "text-down",
            !flash && "text-ink-2",
          )}
        >
          {Math.round(data.price_usd)}
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 border-t border-line-subtle px-3 py-3">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.1em] text-ink-3">
          Solana
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1 font-mono text-[10px] tabular-nums",
            up ? "text-up" : "text-down",
          )}
        >
          {up ? "▲" : "▼"}
          {Math.abs(change).toFixed(2)}%
        </span>
      </div>

      <span
        className={cn(
          "font-mono text-lg font-semibold tabular-nums leading-none",
          "transition-colors duration-500",
          flash === "up" && "text-up",
          flash === "down" && "text-down",
          !flash && "text-ink",
        )}
      >
        ${data.price_usd.toFixed(2)}
      </span>

      <Sparkline points={data.series} up={up} />

      <span className="flex items-center gap-1.5 text-[9px] text-ink-3">
        <span
          className={cn(
            "inline-block h-1 w-1 rounded-full",
            data.stale ? "bg-warn" : "sol-pulse bg-up",
          )}
        />
        {data.stale
          ? `last good price, ${data.age_seconds}s old`
          : "live · 1h"}
      </span>
    </div>
  );
}

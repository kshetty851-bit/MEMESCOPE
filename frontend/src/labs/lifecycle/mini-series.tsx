import { extentOf, pathOf, scaler, segmentsOf, toPoints } from "./chart-geometry";
import { Unavailable, formatNumber } from "./display";
import type { SeriesPoint } from "./types";

const W = 160;
const H = 44;
const PAD = 3;

/**
 * One source's series as a small multiple. Same break-at-null rule as the
 * overlay: a source with a gap shows a gap, and a source with no points says so
 * instead of drawing a flat line along the floor.
 */
export function MiniSeries({
  source,
  points: raw,
  backfillBefore,
}: {
  source: string;
  points: SeriesPoint[];
  backfillBefore: string | null;
}) {
  const points = toPoints(raw);
  const extent = extentOf(points);
  const name = source.replace(/_/g, " ");

  if (!extent) {
    return (
      <div className="flex flex-col gap-1 rounded-md border border-line p-3" data-testid={`mini-${source}`}>
        <span className="text-label font-medium uppercase text-ink-3">{name}</span>
        <Unavailable reason="no points collected from this source" />
      </div>
    );
  }

  const tMin = points[0]!.t;
  const tMax = points[points.length - 1]!.t;
  const span = tMax - tMin || 1;
  const x = (t: number) => PAD + ((t - tMin) / span) * (W - PAD * 2);
  const y = scaler(extent[0], extent[1], PAD, H - PAD);
  const segments = segmentsOf(points, x, y);
  const gaps = points.filter((p) => p.v === null).length;

  const bf = backfillBefore ? Date.parse(backfillBefore) : NaN;
  const bfEdge = Number.isFinite(bf) ? Math.min(Math.max(bf, tMin), tMax) : null;

  return (
    <div className="flex flex-col gap-1 rounded-md border border-line p-3" data-testid={`mini-${source}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-label font-medium uppercase text-ink-3">{name}</span>
        <span data-numeric className="text-xs text-ink-3">
          {formatNumber(String(extent[0]))} – {formatNumber(String(extent[1]))}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={`${name}: ${points.length - gaps} readings${gaps ? `, ${gaps} unavailable` : ""}`}
      >
        {bfEdge !== null && bfEdge > tMin ? (
          <rect
            x={x(tMin)}
            y={0}
            width={x(bfEdge) - x(tMin)}
            height={H}
            fill="var(--color-warn)"
            fillOpacity="0.1"
          />
        ) : null}
        {segments.map((segment, i) =>
          segment.length === 1 ? (
            <circle key={i} cx={segment[0]![0]} cy={segment[0]![1]} r="1.6" fill="var(--color-accent)" />
          ) : (
            <path
              key={i}
              d={pathOf(segment)}
              fill="none"
              stroke="var(--color-accent)"
              strokeWidth="1.25"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ),
        )}
      </svg>
      {gaps > 0 ? (
        <span className="text-xs text-ink-3">{gaps} unavailable (gaps, not zero)</span>
      ) : null}
    </div>
  );
}

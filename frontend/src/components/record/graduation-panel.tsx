"use client";

import { Label, Panel } from "@/components/ui/panel";
import { useGraduations } from "@/hooks/use-graduation";
import type { GraduationAge } from "@/types/graduation";

/**
 * The hour after graduation, measured forward.
 *
 * pump.fun publishes no graduation timestamp, so this cannot be reconstructed
 * from history — every attempt ends up bucketing by CREATION age, which is a
 * different quantity. The collector stamps the event itself and re-reads each
 * coin at fixed ages; this shows the result as it accumulates.
 *
 * Median before mean, deliberately. On this population the mean is carried by a
 * handful of survivors, and a page that led with it would report a rally that
 * almost no coin experienced.
 */

/** "+15m" under an hour, "+6h" above it — 51 rows of "+2880m" is unreadable. */
function ageLabel(minutes: number): string {
  return minutes < 60 ? `+${minutes}m` : `+${minutes / 60}h`;
}

function pctText(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function tone(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return "text-muted";
  return v > 0 ? "text-up" : v < 0 ? "text-down" : "text-ink";
}

function Row({ a }: { a: GraduationAge }) {
  const empty = a.n === 0;
  return (
    <tr className="border-t border-line">
      <td className="py-1.5 pr-3 font-mono text-ink">{ageLabel(a.minutes)}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">{a.n}</td>
      {empty ? (
        <td className="py-1.5 text-xs text-muted" colSpan={4}>
          no readings at this age yet
        </td>
      ) : (
        <>
          <td className={`py-1.5 pr-3 text-right font-mono ${tone(a.median_pct)}`}>
            {pctText(a.median_pct)}
          </td>
          <td className={`py-1.5 pr-3 text-right font-mono ${tone(a.mean_pct)}`}>
            {pctText(a.mean_pct)}
          </td>
          <td className="py-1.5 pr-3 text-right font-mono text-muted">
            {a.pct_up?.toFixed(0)}%
          </td>
          <td className="py-1.5 text-right font-mono text-[10px] text-muted">
            {pctText(a.worst_pct)} … {pctText(a.best_pct)}
          </td>
        </>
      )}
    </tr>
  );
}

export function GraduationPanel() {
  const { data, isLoading, error } = useGraduations();
  // A panel that vanishes on error is indistinguishable from one that was
  // never built — which is exactly how this looked on 2026-09-08 when the page
  // shipped via Vercel minutes before its endpoint reached the backend. Silence
  // is the one thing this must not render.
  if (isLoading) return null;
  if (error || !data) {
    return (
      <Panel density="compact">
        <Label>THE HOUR AFTER GRADUATION</Label>
        <p className="mt-2 text-xs text-muted">
          Not available. The measurement exists but its endpoint did not answer —
          usually the backend running an older build than this page.
        </p>
      </Panel>
    );
  }

  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <Label>THE HOUR AFTER GRADUATION</Label>
        <span className="font-mono text-[10px] text-muted">
          {data.cohort} coins watched graduate
        </span>
      </div>

      {/* 51 rows: dense in the first hour, hourly to two days. Scrolled rather
          than truncated — a hidden row is a measurement the reader cannot know
          was taken. */}
      <div className="mt-3 max-h-96 overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="text-[10px] uppercase tracking-wide text-muted">
            <tr>
              <th className="py-1 pr-3 font-normal">sell at</th>
              <th className="py-1 pr-3 text-right font-normal">n</th>
              <th className="py-1 pr-3 text-right font-normal">median</th>
              <th className="py-1 pr-3 text-right font-normal">mean</th>
              <th className="py-1 pr-3 text-right font-normal">up</th>
              <th className="py-1 text-right font-normal">worst … best</th>
            </tr>
          </thead>
          <tbody>
            {data.ages.map((a) => (
              <Row key={a.minutes} a={a} />
            ))}
          </tbody>
        </table>
      </div>

      {data.excluded_cold_start > 0 ? (
        <p className="mt-3 border-t border-line pt-2 text-[10px] leading-relaxed text-muted">
          {data.excluded_cold_start} coins are excluded: they were already
          graduated when the collector first looked, so their timestamp records
          when we started watching rather than when they graduated. Counting
          them would reintroduce the error this measurement exists to remove.
        </p>
      ) : null}

      <p className="mt-2 text-[10px] leading-relaxed text-muted">{data.disclosure}</p>
    </Panel>
  );
}

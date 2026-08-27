"use client";

import { useState } from "react";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useLabSnapshots } from "@/hooks/use-lab";
import type { LabStrategyRow } from "@/types/lab";

/**
 * FROZEN LEADERBOARDS
 *
 * The live board keeps moving, so by the time anyone reads it the 24-hour
 * snapshot no longer says what the 24-hour snapshot said. These are the
 * immutable copies taken at each boundary and never rewritten — the only place
 * a result can be read as of a moment rather than as of now.
 *
 * Deliberately narrow: six columns, not twenty-five, because this is the view
 * someone opens on a phone to answer "what did it actually do?". The full board
 * is one tap away and has the rest.
 */

function pct(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : `${v.toFixed(digits)}%`;
}

function money(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : `$${v.toFixed(2)}`;
}

function num(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : v.toFixed(digits);
}

/**
 * Sample size, stated rather than implied.
 *
 * A strategy leading on five closed trades is leading on noise, and the number
 * beside the return is the only thing that says so.
 */
function confidence(trades: number): string {
  if (trades >= 100) return "meaningful";
  if (trades >= 30) return "thin";
  return "noise";
}

export default function StrategyLabSnapshotsPage() {
  const { data, isLoading, error } = useLabSnapshots();
  const [selected, setSelected] = useState<string | null>(null);

  if (error) return <ErrorState body="Frozen snapshots are unavailable." />;
  if (isLoading || !data) return <Skeleton className="h-96 w-full" />;

  const snapshots = data.snapshots ?? [];
  const active =
    snapshots.find((s) => s.label === selected) ?? snapshots[snapshots.length - 1];
  const rows: LabStrategyRow[] = (active?.payload?.strategies ?? [])
    .slice()
    .sort((a, b) => (b.equity ?? 0) - (a.equity ?? 0));

  return (
    <div className="space-y-4">
      <Panel density="compact">
        <Label>V6 STRATEGY LAB — FROZEN SNAPSHOTS</Label>
        <h1 className="mt-1 text-lg font-medium text-ink">
          The board as it stood, not as it stands
        </h1>
        <p className="mt-1 text-xs leading-relaxed text-muted">
          Each of these was written once at its boundary and is never rewritten.
          The live leaderboard has moved since; that is the point of keeping
          these.
        </p>
        {snapshots.length === 0 ? (
          <p className="mt-3 text-xs text-warn">
            No snapshot has been taken yet. The first lands at the 24-hour
            boundary and appears here on its own.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
            {snapshots.map((s) => (
              <button
                key={s.label}
                onClick={() => setSelected(s.label)}
                className={`rounded border px-2 py-1 text-xs ${
                  active?.label === s.label
                    ? "border-accent text-accent"
                    : "border-line text-muted hover:text-ink"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        )}
      </Panel>

      {active ? (
        <Panel density="compact">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <Label>{active.label} — FROZEN LEADERBOARD</Label>
            <p className="font-mono text-[10px] text-muted">
              boundary{" "}
              {new Date(active.boundary_at)
                .toISOString()
                .replace("T", " ")
                .slice(0, 16)}
              Z · {num(active.elapsed_hours, 1)}h ·{" "}
              {active.payload?.total_closed_trades ?? 0} closed trades
            </p>
          </div>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3 font-normal">#</th>
                  <th className="py-1 pr-3 font-normal">Strategy</th>
                  <th className="py-1 pr-3 text-right font-normal">Equity</th>
                  <th className="py-1 pr-3 text-right font-normal">Return</th>
                  <th className="py-1 pr-3 text-right font-normal">Trades</th>
                  <th className="py-1 pr-3 text-right font-normal">Win %</th>
                  <th className="py-1 pr-3 text-right font-normal">PF</th>
                  <th className="py-1 pr-3 font-normal">Sample</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.strategy_id} className="border-t border-line/40">
                    <td className="py-1 pr-3 text-muted">{i + 1}</td>
                    <td className="whitespace-nowrap py-1 pr-3 font-mono text-ink">
                      {r.strategy_id}{" "}
                      <span className="text-muted">{r.name}</span>
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums text-ink">
                      {money(r.equity)}
                    </td>
                    <td
                      className={`py-1 pr-3 text-right tabular-nums ${
                        (r.return_pct ?? 0) < 0 ? "text-warn" : "text-ink"
                      }`}
                    >
                      {pct(r.return_pct)}
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums text-ink">
                      {r.trades}
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums text-ink">
                      {pct(r.win_pct, 1)}
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums text-ink">
                      {num(r.profit_factor, 2)}
                    </td>
                    <td className="py-1 pr-3 text-muted">
                      {confidence(r.trades ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 border-t border-line pt-2 text-[10px] leading-relaxed text-muted">
            Read the SAMPLE column before the return. A strategy leading on a
            handful of closed trades is leading on luck, and the 30-day review is
            the gate that was written for exactly that reason.
          </p>
        </Panel>
      ) : null}
    </div>
  );
}

"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Tooltip } from "@/components/ui/tooltip";
import { useLabLeaderboard } from "@/hooks/use-strategy-lab";
import {
  LAB_WINDOWS,
  multiple,
  plain,
  type LabMode,
  type LabRow,
  type LabWindow,
} from "@/lib/strategy-lab";
import { cn } from "@/lib/utils";

import {
  DatasetFooter,
  FlagChips,
  Money,
  Percent,
  SampleCount,
  SectionNote,
} from "./shared";

/**
 * THE LEADERBOARD.
 *
 * Ranked by `lab_score`, never by win rate — §11 forbids the latter and the
 * reason is on the page rather than in a doc: a strategy that wins ninety
 * percent of the time and loses money on the tenth is not a good strategy.
 *
 * Sample size is the second column, not a footnote. A record of four trades and
 * a record of two thousand must never look alike, so N is rendered at value
 * size and turns amber below the threshold.
 *
 * Every underlying metric is shown beside the score. The score is a summary,
 * not a replacement — §11's "do NOT hide the underlying metrics".
 */

const COLUMNS: { key: string; label: string; hint?: string; numeric?: boolean }[] = [
  { key: "rank", label: "#" },
  { key: "strategy", label: "Strategy" },
  { key: "n", label: "N", hint: "Trades taken. Below the threshold this turns amber.", numeric: true },
  { key: "equity", label: "Final equity", hint: "Simulated. Starts at $1,000.", numeric: true },
  { key: "return", label: "Return", numeric: true },
  { key: "pf", label: "PF", hint: "Profit factor: gross wins ÷ gross losses.", numeric: true },
  { key: "exp", label: "Expectancy", hint: "Mean net P&L per trade.", numeric: true },
  { key: "win", label: "Win rate", hint: "Shown, never ranked on.", numeric: true },
  { key: "median", label: "Median trade", hint: "Beside the mean, because one monster token moves the mean.", numeric: true },
  { key: "dd", label: "Max DD", hint: "Peak-to-trough on the mark-to-market curve.", numeric: true },
  { key: "rug", label: "Rug loss", numeric: true },
  { key: "rugs", label: "Rugs", numeric: true },
  { key: "blocked", label: "Capital blocked", hint: "Entries refused for want of cash, at entry size.", numeric: true },
  { key: "capture", label: "Capture", hint: "Share of offered opportunities actually taken.", numeric: true },
  { key: "conc", label: "Avg / peak open", numeric: true },
  { key: "hold", label: "Avg hold", numeric: true },
  { key: "m2", label: "2x", hint: "Positions turned into a 2x or better.", numeric: true },
  { key: "m5", label: "5x", numeric: true },
  { key: "m10", label: "10x", numeric: true },
  { key: "moon", label: "Moonshot eff.", hint: "Realised ÷ defensibly executable upside on tokens that reached 2x.", numeric: true },
  { key: "score", label: "Lab score", numeric: true },
];

function moon(row: LabRow, level: number) {
  return row.moonshots.find((m) => m.level === level) ?? null;
}

function hold(minutes: number | null): string {
  if (minutes === null) return "—";
  if (minutes < 90) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

export function Leaderboard({
  mode,
  window,
  onWindowChange,
  onSelect,
}: {
  mode: LabMode;
  window: LabWindow;
  onWindowChange: (w: LabWindow) => void;
  onSelect: (strategyId: string) => void;
}) {
  const { data, isPending, error, refetch } = useLabLeaderboard(mode, window);

  return (
    <Panel density="flush">
      <PanelHeader className="flex flex-wrap items-center justify-between gap-3 px-4 pt-4">
        <div>
          <PanelTitle>Leaderboard</PanelTitle>
          <p className="mt-0.5 text-xs text-ink-3">
            Ranked by risk-adjusted wallet outcome. Never by win rate.
          </p>
        </div>
        <div
          role="group"
          aria-label="Leaderboard window"
          className="flex flex-wrap gap-1 rounded-md border border-line bg-raised/50 p-1"
        >
          {LAB_WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => onWindowChange(w)}
              aria-pressed={w === window}
              className={cn(
                "rounded-sm px-2.5 py-1 text-label font-medium transition-colors",
                w === window
                  ? "bg-surface text-ink shadow-e1"
                  : "text-ink-3 hover:text-ink",
              )}
            >
              {w}
            </button>
          ))}
        </div>
      </PanelHeader>

      <div className="space-y-2 px-4 pb-3">
        <SectionNote>{data?.ranking ?? "Loading ranking definition…"}</SectionNote>
        {window !== "ALL" && data ? <SectionNote>{data.window_note}</SectionNote> : null}
      </div>

      {error ? (
        <ErrorState
          body="The leaderboard could not be loaded."
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <div className="space-y-2 px-4 pb-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : !data?.rows.length ? (
        <p className="px-4 pb-6 text-sm text-ink-3">
          No results for this window yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1600px] border-collapse text-sm">
            <thead>
              <tr className="border-y border-line bg-raised/40 text-left">
                {COLUMNS.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={cn(
                      "whitespace-nowrap px-3 py-2 text-label font-semibold uppercase tracking-wide text-ink-3",
                      column.numeric && "text-right",
                    )}
                  >
                    {column.hint ? (
                      <Tooltip content={column.hint} side="bottom">
                        <span className="cursor-help border-b border-dotted border-ink-4">
                          {column.label}
                        </span>
                      </Tooltip>
                    ) : (
                      column.label
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => {
                const m2 = moon(row, 2);
                return (
                  <tr
                    key={`${row.strategy_id}@${row.version}`}
                    className="border-b border-line/60 transition-colors hover:bg-raised/40"
                  >
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-3">
                      {row.rank}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => onSelect(row.strategy_id)}
                        className="group flex flex-col items-start gap-0.5 text-left"
                      >
                        <span className="flex items-center gap-2">
                          <span className="font-mono font-semibold text-ink group-hover:text-accent">
                            {row.strategy_id}
                          </span>
                          {row.benchmark ? (
                            <span className="rounded-sm border border-line px-1 py-px text-[10px] uppercase text-ink-3">
                              Benchmark
                            </span>
                          ) : null}
                        </span>
                        <span className="text-xs text-ink-3 group-hover:text-ink-2">
                          {row.name} · v{row.version}
                        </span>
                        <FlagChips flags={row.flags} />
                      </button>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <SampleCount n={row.n} threshold={data.small_sample_threshold} />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Money value={row.final_equity} />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Percent value={row.wallet_return_pct} />
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {row.profit_factor === null ? "∞" : plain(row.profit_factor)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Money value={row.expectancy} signed />
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {row.win_rate_pct === null ? "—" : `${row.win_rate_pct.toFixed(0)}%`}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Percent value={row.median_trade_return_pct} />
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-down">
                      {row.max_drawdown_pct.toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Money value={-Math.abs(row.rug_loss_usd)} signed />
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {row.rugs}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Money value={row.capital_blocked_usd} digits={0} />
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {row.capture_pct.toFixed(0)}%
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {row.avg_concurrency.toFixed(1)} / {row.peak_concurrency}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {hold(row.avg_hold_minutes)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {moon(row, 2)?.captured ?? 0}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {moon(row, 5)?.captured ?? 0}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {moon(row, 10)?.captured ?? 0}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {m2?.efficiency_pct === null || m2 === null
                        ? "—"
                        : `${m2.efficiency_pct.toFixed(0)}%`}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Tooltip
                        side="top"
                        content={`R ${row.score_components.robust_return_pct.toFixed(1)}% · D ${(row.score_components.drawdown * 100).toFixed(0)}% · S ${row.score_components.sample_shrink.toFixed(2)} · P ${row.score_components.profit_factor_multiplier.toFixed(2)}`}
                      >
                        <span
                          className={cn(
                            "cursor-help font-mono text-md font-semibold tabular-nums",
                            row.lab_score >= 0 ? "text-up" : "text-down",
                          )}
                        >
                          {row.lab_score.toFixed(1)}
                        </span>
                      </Tooltip>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <DatasetFooter dataset={data?.dataset ?? null} />
    </Panel>
  );
}

export { multiple };

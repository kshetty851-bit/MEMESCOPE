"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";

import { TrackerChart } from "./chart";
import {
  CLOSE_REASON_LABELS,
  COMPONENT_LABELS,
  COMPONENT_ORDER,
  count,
  crore,
  day,
  inr,
  plainPct,
  pct,
  STATE_CLASS,
  STATE_LABEL,
  TONE_CLASS,
  tone,
} from "./format";
import { useStock } from "./hooks";

/**
 * One stock: the chart with its resistance ladder, the score taken apart, and
 * every episode it has ever had.
 *
 * The clusters are drawn from `bt_states`, which is what the machine actually
 * saw on the last bar — not recomputed here. A panel that recomputes can draw
 * a level the state machine never used, and then the chart and the board
 * disagree about the same stock.
 */

const NEAR_PCT_FALLBACK = 4;

export function StockPanel({
  symbol,
  nearPct = NEAR_PCT_FALLBACK,
  onClose,
}: {
  symbol: string;
  nearPct?: number;
  onClose: () => void;
}) {
  const query = useStock(symbol);

  return (
    <Panel density="flush" data-testid="stock-panel">
      <PanelHeader className="flex items-center justify-between px-4 pt-3">
        <PanelTitle>
          {symbol}
          {query.data?.stock.name ? (
            <span className="ml-2 font-normal text-ink-3">
              {query.data.stock.name}
            </span>
          ) : null}
        </PanelTitle>
        <button
          type="button"
          onClick={onClose}
          className="text-label uppercase text-ink-4 hover:text-ink-2"
        >
          Close
        </button>
      </PanelHeader>

      {query.isLoading ? (
        <Skeleton className="m-4 h-64" />
      ) : !query.data ? (
        <EmptyState
          title="Nothing stored for this stock"
          body="It is in the universe but the detection pass has not reached it, or it has fewer than 250 daily bars and is excluded from levels."
        />
      ) : (
        <div className="space-y-4 p-4">
          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <TrackerChart
              candles={query.data.candles}
              clusters={query.data.levels?.clusters ?? []}
              nearestResistance={query.data.levels?.nearest_resistance ?? null}
              nearPct={nearPct}
              episode={query.data.episode}
            />

            <div className="space-y-3">
              {query.data.score ? (
                <>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-lg tabular-nums text-ink">
                      {query.data.score.score}
                    </span>
                    <span
                      className={`rounded border px-1.5 py-0.5 text-label uppercase ${
                        STATE_CLASS[query.data.score.state] ?? STATE_CLASS.NONE
                      }`}
                    >
                      {STATE_LABEL[query.data.score.state] ?? query.data.score.state}
                    </span>
                    <span className="text-label uppercase text-ink-4">
                      {query.data.score.days_in_state}d
                    </span>
                  </div>
                  {/* The five components, drawn as bars. A score nobody can
                      take apart is a number nobody can argue with. */}
                  <dl className="space-y-1.5" data-testid="score-components">
                    {COMPONENT_ORDER.filter(
                      (name) => name in (query.data?.score?.components ?? {}),
                    ).map((name) => {
                      const value = query.data!.score!.components[name] ?? 0;
                      return (
                        <div key={name} className="flex items-center gap-2">
                          <dt className="w-24 text-label uppercase text-ink-4">
                            {COMPONENT_LABELS[name] ?? name}
                          </dt>
                          <dd className="flex-1">
                            <div className="h-1.5 rounded bg-surface-2">
                              <div
                                className="h-1.5 rounded bg-accent"
                                style={{ width: `${Math.round(value * 100)}%` }}
                              />
                            </div>
                          </dd>
                          <span className="w-8 text-right font-mono text-xs tabular-nums text-ink-3">
                            {Math.round(value * 100)}
                          </span>
                        </div>
                      );
                    })}
                  </dl>
                </>
              ) : (
                <p className="text-sm text-ink-3">
                  No score: fewer than 250 daily bars, so this stock is in the
                  universe and out of the levels.
                </p>
              )}

              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-3">
                <Field label="Resistance"
                  value={inr(query.data.levels?.nearest_resistance)} />
                <Field label="Distance"
                  value={plainPct(query.data.score?.distance_pct, 2)} />
                <Field label="52w high" value={inr(query.data.levels?.week52_high)} />
                <Field label="ATR(14)" value={inr(query.data.levels?.atr)} />
                <Field label="20d range"
                  value={plainPct(query.data.levels?.range_pct)} />
                <Field label="Turnover"
                  value={crore(query.data.stock.turnover_20d)} />
                <Field label="Bars" value={count(query.data.stock.bars)} />
                <Field label="Series" value={query.data.stock.series} />
              </dl>
            </div>
          </div>

          <div>
            <p className="mb-2 text-label uppercase text-ink-4">
              Episodes ({query.data.history.length})
            </p>
            {query.data.history.length === 0 ? (
              <p className="text-sm text-ink-3">
                No setup has opened on this stock yet. Episodes open on the
                first WATCH or NEAR bar.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-label uppercase text-ink-4">
                    <tr className="border-b border-line">
                      <th className="py-2 pr-3 text-left">Opened</th>
                      <th className="px-3 py-2 text-left">Source</th>
                      <th className="px-3 py-2 text-right">Score</th>
                      <th className="px-3 py-2 text-right">Ref</th>
                      <th className="px-3 py-2 text-left">Broke out</th>
                      <th className="px-3 py-2 text-right">+20d ref</th>
                      <th className="px-3 py-2 text-right">+20d break</th>
                      <th className="py-2 pl-3 text-left">Ended</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono tabular-nums">
                    {query.data.history.map((episode) => (
                      <tr key={episode.id} data-testid="episode-row"
                        className="border-b border-line/50">
                        <td className="py-2 pr-3 text-left text-ink-2">
                          {day(episode.opened)}
                        </td>
                        <td className="px-3 py-2 text-left text-ink-4">
                          {episode.source}
                        </td>
                        <td className="px-3 py-2 text-right text-ink-2">
                          {episode.max_score}
                        </td>
                        <td className="px-3 py-2 text-right text-ink-3">
                          {inr(episode.ref_price)}
                        </td>
                        <td className="px-3 py-2 text-left text-ink-3">
                          {episode.breakout_date ? day(episode.breakout_date) : "—"}
                        </td>
                        <td className={`px-3 py-2 text-right ${
                          TONE_CLASS[tone(episode.ret_ref_20)]}`}>
                          {pct(episode.ret_ref_20)}
                        </td>
                        <td className={`px-3 py-2 text-right ${
                          TONE_CLASS[tone(episode.ret_bo_20)]}`}>
                          {pct(episode.ret_bo_20)}
                        </td>
                        <td className="py-2 pl-3 text-left text-ink-4">
                          {episode.close_reason
                            ? (CLOSE_REASON_LABELS[episode.close_reason]
                               ?? episode.close_reason)
                            : "open"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-label uppercase text-ink-4">{label}</dt>
      <dd className="font-mono text-xs tabular-nums text-ink-2">{value}</dd>
    </div>
  );
}

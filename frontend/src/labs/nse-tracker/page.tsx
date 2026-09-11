"use client";

import { useMemo, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";

import { MOCK } from "./api";
import {
  count,
  crore,
  day,
  inr,
  plainPct,
  pct,
  STATE_CLASS,
  STATE_LABEL,
  STATE_ORDER,
  TONE_CLASS,
  tone,
} from "./format";
import { useBreakouts, useHealth, useNear, useStats } from "./hooks";
import { OutcomesCard } from "./outcomes";
import { StockPanel } from "./stock-panel";

/**
 * NSE BREAKOUT TRACKER
 *
 * Indian equities walking up into a daily resistance level they have not
 * cleared yet, and what happened to the ones that did.
 *
 * **There is no book here.** No wallet, no orders, no paper ledger — this
 * watches and records, and the only thing it can tell you is what the history
 * says. The header says so rather than a footnote, because a reader who
 * assumed otherwise would draw a conclusion about money that does not exist.
 *
 * Every figure is served already computed. Nothing on this page recomputes a
 * score, a distance or a return — a second implementation is a second answer,
 * and the first time either changed they would disagree. The one exception is
 * the board's sort, and even that reads the same state order the backend
 * publishes.
 *
 * The panel that matters is the last one. The replay says the score ranks
 * which setups CLEAR their level very well, and does not predict the return at
 * all. Both halves are on the page.
 */

const BREAKOUT_WINDOWS = [7, 30, 90];

export function NseTrackerPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [window, setWindow] = useState(BREAKOUT_WINDOWS[1]!);

  const health = useHealth();
  const running = health.data?.running ?? false;

  const near = useNear(running);
  const breakouts = useBreakouts(window, "live", running);
  const replayStats = useStats("replay", running);
  const liveStats = useStats("live", running);

  const rows = useMemo(
    () =>
      [...(near.data ?? [])].sort(
        (a, b) =>
          (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9) ||
          b.score - a.score,
      ),
    [near.data],
  );
  const nearPct = replayStats.data?.config?.near_pct;

  if (health.isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (!running) {
    return (
      <Panel density="comfortable">
        <PanelHeader>
          <PanelTitle>NSE Breakout Tracker</PanelTitle>
        </PanelHeader>
        <EmptyState
          title="The tracker is not running"
          body="NSE_BREAKOUT_ENABLED is off, so no bhavcopy is being ingested and no state is being recorded. This is different from a tracker that ran and found nothing."
        />
      </Panel>
    );
  }

  const coverage = health.data?.coverage;

  return (
    <div className="space-y-4">
      {/* 1 — the header strip */}
      <Panel density="compact">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            <h1 className="font-mono text-sm text-ink">NSE Breakout Tracker</h1>
            <span className="rounded border border-line bg-surface-2 px-1.5 py-0.5 text-label uppercase text-ink-3">
              watch only
            </span>
            {MOCK && (
              <span className="rounded border border-warn/40 bg-warn/15 px-1.5 py-0.5 text-label uppercase text-warn">
                mock data
              </span>
            )}
          </div>
          <Stat label="Universe"
            value={health.data?.universe
              ? `${count(health.data.universe.active)} active` : "—"} />
          <Stat label="Scorable"
            value={coverage
              ? `${count(coverage.symbols_covered)} (${plainPct(coverage.pct)})`
              : "—"} />
          <Stat label="Last bar" value={day(coverage?.last_bar)} />
          <Stat label="Bars" value={count(coverage?.bars_total)} />
          <Stat label="Failed days"
            value={count(health.data?.bhavcopy?.days_failed)} />
          <Stat label="Flagged bars"
            value={count(health.data?.corporate_actions?.suspect_gap_bars)} />
        </div>
        {health.data?.bhavcopy?.failed_days?.length ? (
          <p role="alert" className="mt-3 rounded border border-down/40 bg-down/10 px-3 py-2 text-xs text-down">
            {health.data.bhavcopy.failed_days.length} day(s) failed to ingest:{" "}
            {health.data.bhavcopy.failed_days.map((d) => d.date).join(", ")}. The
            levels for those sessions are computed without them.
          </p>
        ) : null}
      </Panel>

      {/* 2 — the near-breakout board */}
      <Panel density="flush">
        <PanelHeader className="flex items-center justify-between px-4 pt-3">
          <PanelTitle>Near breakout</PanelTitle>
          <span className="text-label uppercase text-ink-4">
            {rows.filter((r) => r.state === "NEAR").length} near ·{" "}
            {rows.filter((r) => r.state === "WATCH").length} watch
          </span>
        </PanelHeader>
        {near.isLoading ? (
          <Skeleton className="m-4 h-40" />
        ) : rows.length === 0 ? (
          <EmptyState
            title="Nothing is near a level today"
            body="A stock reaches WATCH at score 60 within 10% of its nearest unbroken resistance, and NEAR at score 70 within 4%. On a quiet day neither happens."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-label uppercase text-ink-4">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 text-left">Stock</th>
                  <th className="px-3 py-2 text-left">State</th>
                  <th className="px-3 py-2 text-right">Score</th>
                  <th className="px-3 py-2 text-right">Close</th>
                  <th className="px-3 py-2 text-right">Resistance</th>
                  <th className="px-3 py-2 text-right">Distance</th>
                  <th className="px-3 py-2 text-center">Tight</th>
                  <th className="px-3 py-2 text-center">52w</th>
                  <th className="px-3 py-2 text-right">Days</th>
                  <th className="px-4 py-2 text-right">Turnover</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {rows.map((row) => (
                  <tr
                    key={row.symbol}
                    data-testid="near-row"
                    onClick={() => setSelected(row.symbol)}
                    className={`cursor-pointer border-b border-line/50 hover:bg-surface-2 ${
                      selected === row.symbol ? "bg-surface-2" : ""
                    }`}
                  >
                    <td className="px-4 py-2 text-left">
                      <span className="text-ink">{row.symbol}</span>
                      {row.name ? (
                        <span className="ml-2 font-sans text-ink-4">
                          {row.name}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        data-testid="state-badge"
                        className={`rounded border px-1.5 py-0.5 text-label uppercase ${
                          STATE_CLASS[row.state] ?? STATE_CLASS.NONE
                        }`}
                      >
                        {STATE_LABEL[row.state] ?? row.state}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right text-ink">{row.score}</td>
                    <td className="px-3 py-2 text-right text-ink-2">
                      {inr(row.close)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {inr(row.resistance)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-2">
                      {plainPct(row.distance_pct, 2)}
                    </td>
                    <td className="px-3 py-2 text-center text-ink-3">
                      {row.tightness ? (
                        <span data-testid="tight-marker">◆</span>
                      ) : (
                        <span className="text-ink-4">·</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-center text-ink-3">
                      {row.is_52w_high ? (
                        <span data-testid="high-marker" className="text-warn">
                          ▲
                        </span>
                      ) : (
                        <span className="text-ink-4">·</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {row.days_in_state}
                    </td>
                    <td className="px-4 py-2 text-right text-ink-3">
                      {crore(row.turnover_20d)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* 3 — the stock view */}
      {selected && (
        <StockPanel
          symbol={selected}
          nearPct={nearPct}
          onClose={() => setSelected(null)}
        />
      )}

      {/* 4 — recent breakouts */}
      <Panel density="flush">
        <PanelHeader className="flex items-center justify-between px-4 pt-3">
          <PanelTitle>Recent breakouts</PanelTitle>
          <div className="flex gap-1">
            {BREAKOUT_WINDOWS.map((days) => (
              <button
                key={days}
                type="button"
                onClick={() => setWindow(days)}
                className={`rounded border px-2 py-0.5 text-label uppercase ${
                  window === days
                    ? "border-accent/40 bg-accent/10 text-accent"
                    : "border-line text-ink-4 hover:text-ink-2"
                }`}
              >
                {days}d
              </button>
            ))}
          </div>
        </PanelHeader>
        {breakouts.isLoading ? (
          <Skeleton className="m-4 h-32" />
        ) : (breakouts.data ?? []).length === 0 ? (
          <EmptyState
            title="No confirmed breakouts in this window"
            body="A breakout needs a daily close more than 1% through the level on at least 1.5× the 20-day mean volume. Roughly 30% of setups ever get one."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-label uppercase text-ink-4">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 text-left">Stock</th>
                  <th className="px-3 py-2 text-left">Date</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-right">Level</th>
                  <th className="px-3 py-2 text-right">Volume</th>
                  <th className="px-3 py-2 text-right">Since</th>
                  <th className="px-3 py-2 text-right">Max gain</th>
                  <th className="px-3 py-2 text-right">Max DD</th>
                  <th className="px-4 py-2 text-left">Held?</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {(breakouts.data ?? []).map((row) => (
                  <tr
                    key={`${row.symbol}-${row.breakout_date}`}
                    data-testid="breakout-row"
                    onClick={() => setSelected(row.symbol)}
                    className="cursor-pointer border-b border-line/50 hover:bg-surface-2"
                  >
                    <td className="px-4 py-2 text-left text-ink">{row.symbol}</td>
                    <td className="px-3 py-2 text-left text-ink-3">
                      {day(row.breakout_date)}
                      <span className="ml-1 text-ink-4">({row.days_since}d)</span>
                    </td>
                    <td className="px-3 py-2 text-right text-ink-2">
                      {inr(row.breakout_price)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {inr(row.resistance)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {row.volume_mult === null ? "—" : `${row.volume_mult.toFixed(1)}×`}
                    </td>
                    <td
                      data-testid="ret-since"
                      className={`px-3 py-2 text-right ${
                        TONE_CLASS[tone(row.ret_since_pct)]
                      }`}
                    >
                      {pct(row.ret_since_pct)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {pct(row.max_gain_pct)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {pct(row.max_drawdown_pct)}
                    </td>
                    <td className="px-4 py-2 text-left">
                      {row.false_breakout ? (
                        <span
                          data-testid="false-flag"
                          className="rounded border border-down/30 bg-down/10 px-1.5 py-0.5 text-label uppercase text-down"
                        >
                          false
                        </span>
                      ) : (
                        <span className="text-ink-4">held</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* 5 — what any of it was worth */}
      <OutcomesCard replay={replayStats.data} live={liveStats.data} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-label uppercase text-ink-4">{label}</p>
      <p className="font-mono text-sm tabular-nums text-ink">{value}</p>
    </div>
  );
}

"use client";

import { useMemo, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";
import { shortenAddress } from "@/lib/format";

import { CLOSE_REASON_LABELS, EXIT_LABELS, MOCK } from "./api";
import { EquityCurve } from "./equity-curve";
import {
  compactUsd,
  hours as fmtHours,
  plainPct,
  pct,
  price,
  rate,
  signedUsd,
  STATE_CLASS,
  STATE_LABEL,
  STATE_ORDER,
  TONE_CLASS,
  tone,
  usd,
} from "./format";
import {
  useAccount,
  useEpisodes,
  useEquity,
  useHealth,
  usePositions,
  useSetups,
  useStats,
  useTradeStats,
  useTrades,
} from "./hooks";
import { TokenPanel } from "./token-panel";

/**
 * BREAKOUT LAB
 *
 * Established Solana tokens — pools older than a week — coiling into a daily
 * resistance level, and a $1,000 paper book that buys the pre-breakout zone
 * with ten slots and a 25% trailing stop.
 *
 * **This is paper. It is not the Paper Wallet and it is not real money.** The
 * page says so in the header rather than in a footnote, because a reader who
 * confused the two would draw a conclusion about money that does not exist.
 *
 * Every figure is served already computed. Nothing here recomputes a score, a
 * distance, an expectancy or a drawdown — a second implementation would be a
 * second answer, and the first time either changed they would disagree. The
 * one exception is sorting, and even that reads the same state order the
 * backend publishes.
 *
 * The panel that matters most is the last one: setup outcomes by score
 * decile. If the score predicts anything, the top deciles beat the bottom
 * ones. Every lab in this repo so far has answered no.
 */

const STARTING_EQUITY = 1_000;
const PAGE_SIZE = 25;
const EQUITY_WINDOWS: { label: string; hours: number }[] = [
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
  { label: "30d", hours: 720 },
];

function Stat({
  label,
  value,
  toneKey,
}: {
  label: string;
  value: string;
  toneKey?: "up" | "down" | "flat";
}) {
  return (
    <div>
      <p className="text-label uppercase text-ink-4">{label}</p>
      <p
        className={`font-mono text-sm tabular-nums ${
          toneKey ? TONE_CLASS[toneKey] : "text-ink"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

export function BreakoutLabPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [tradePage, setTradePage] = useState(0);
  const [episodePage, setEpisodePage] = useState(0);
  const [window, setWindow] = useState(EQUITY_WINDOWS[1]!.hours);

  const health = useHealth();
  const running = health.data?.running ?? false;

  const setups = useSetups(running);
  const account = useAccount(running);
  const positions = usePositions(running);
  const trades = useTrades(PAGE_SIZE, tradePage * PAGE_SIZE, running);
  const episodes = useEpisodes(PAGE_SIZE, episodePage * PAGE_SIZE, running);
  const equity = useEquity(window, running);
  const stats = useStats(running);
  const tradeStats = useTradeStats(running);

  const rows = useMemo(
    () =>
      [...(setups.data ?? [])].sort(
        (a, b) =>
          (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9) ||
          b.score - a.score,
      ),
    [setups.data],
  );

  const selectedPosition =
    positions.data?.find((p) => p.mint === selected) ?? null;
  const selectedTrades =
    trades.data?.items.filter((t) => t.mint === selected) ?? [];

  if (health.isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (!running) {
    return (
      <Panel density="comfortable">
        <PanelHeader>
          <PanelTitle>Breakout Lab</PanelTitle>
        </PanelHeader>
        <EmptyState
          title="The lab is not running"
          body="BREAKOUT_LAB_ENABLED is off, so nothing is being watched and nothing is being recorded. This is different from a lab that ran and found nothing."
        />
      </Panel>
    );
  }

  return (
    <div className="space-y-4">
      {/* 1 — the header strip */}
      <Panel density="compact">
        {account.data?.halted && (
          <div
            role="alert"
            className="mb-3 rounded border border-down/50 bg-down/15 px-3 py-2 text-sm text-down"
          >
            HALTED — the kill switch tripped at{" "}
            {plainPct(account.data.drawdown_pct)} drawdown. No new positions
            until an operator runs <code>trader reset-halt --yes</code>.
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            <h1 className="font-mono text-sm text-ink">Breakout Lab</h1>
            <span className="rounded border border-line bg-surface-2 px-1.5 py-0.5 text-label uppercase text-ink-3">
              paper
            </span>
            {MOCK && (
              <span className="rounded border border-warn/40 bg-warn/15 px-1.5 py-0.5 text-label uppercase text-warn">
                mock data
              </span>
            )}
            {!account.data?.trading_enabled && (
              <span className="rounded border border-line px-1.5 py-0.5 text-label uppercase text-ink-4">
                trading off
              </span>
            )}
          </div>
          <Stat label="Equity" value={usd(account.data?.equity)} />
          <Stat
            label="Unrealised"
            value={signedUsd(account.data?.unrealised)}
            toneKey={tone(account.data?.unrealised)}
          />
          <Stat label="Drawdown" value={plainPct(account.data?.drawdown_pct)} />
          <Stat
            label="Slots"
            value={
              account.data
                ? `${account.data.slots_used}/${account.data.slots}`
                : "—"
            }
          />
          <Stat label="Slot size" value={usd(account.data?.slot_size)} />
          <Stat
            label="Universe"
            value={
              health.data?.universe
                ? `${health.data.universe.active} active`
                : "—"
            }
          />
          <Stat
            label="Last tick"
            value={
              health.data?.last_run?.candles
                ? fmtHours(health.data.last_run.candles.age_seconds / 3600)
                : "—"
            }
          />
        </div>
      </Panel>

      {/* 2 — the watchlist */}
      <Panel density="flush">
        <PanelHeader className="px-4 pt-3">
          <PanelTitle>Setups</PanelTitle>
          <span className="text-label uppercase text-ink-4">
            {rows.length} open
          </span>
        </PanelHeader>
        {setups.isLoading ? (
          <Skeleton className="m-4 h-32" />
        ) : rows.length === 0 ? (
          <EmptyState
            title="Nothing is set up"
            body="No token in the universe is inside the watch zone with enough momentum. That is the normal state most hours."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-label uppercase text-ink-4">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 text-left">Token</th>
                  <th className="px-3 py-2 text-left">State</th>
                  <th className="px-3 py-2 text-right">Score</th>
                  <th className="px-3 py-2 text-right">To resist.</th>
                  <th className="px-3 py-2 text-right">Open</th>
                  <th className="px-3 py-2 text-right">Liquidity</th>
                  <th className="px-4 py-2 text-right">24h vol</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {rows.map((row) => (
                  <tr
                    key={row.mint}
                    data-testid="setup-row"
                    onClick={() => setSelected(row.mint)}
                    className={`cursor-pointer border-b border-line/50 hover:bg-surface-2 ${
                      selected === row.mint ? "bg-surface-2" : ""
                    }`}
                  >
                    <td className="px-4 py-2 text-left text-ink">
                      {row.symbol ?? shortenAddress(row.mint)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded border px-1.5 py-0.5 text-label uppercase ${
                          STATE_CLASS[row.state] ?? STATE_CLASS.NONE
                        }`}
                      >
                        {STATE_LABEL[row.state] ?? row.state}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right text-ink">{row.score}</td>
                    <td className="px-3 py-2 text-right text-ink-2">
                      {plainPct(row.distance_pct, 2)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {fmtHours(row.hours_open)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-3">
                      {compactUsd(row.liquidity_usd)}
                    </td>
                    <td className="px-4 py-2 text-right text-ink-3">
                      {compactUsd(row.volume_24h_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* 3 — the token panel */}
      {selected && (
        <TokenPanel
          mint={selected}
          onClose={() => setSelected(null)}
          position={selectedPosition}
          trades={selectedTrades}
        />
      )}

      {/* 4 — positions and the curve */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel density="flush">
          <PanelHeader className="px-4 pt-3">
            <PanelTitle>Positions</PanelTitle>
          </PanelHeader>
          {(positions.data ?? []).length === 0 ? (
            <EmptyState
              title="No open positions"
              body="The book buys only when an episode transitions into PRE_BREAKOUT."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-label uppercase text-ink-4">
                  <tr className="border-b border-line">
                    <th className="px-4 py-2 text-left">Token</th>
                    <th className="px-3 py-2 text-right">Entry</th>
                    <th className="px-3 py-2 text-right">Mark</th>
                    <th className="px-3 py-2 text-right">Value</th>
                    <th className="px-3 py-2 text-right">High water</th>
                    <th className="px-3 py-2 text-right">Trail stop</th>
                    <th className="px-3 py-2 text-right">Unreal.</th>
                    <th className="px-4 py-2 text-right">Held</th>
                  </tr>
                </thead>
                <tbody className="font-mono tabular-nums">
                  {(positions.data ?? []).map((row) => (
                    <tr key={row.mint} className="border-b border-line/50">
                      <td className="px-4 py-2 text-left text-ink">
                        {row.symbol ?? shortenAddress(row.mint)}
                      </td>
                      <td className="px-3 py-2 text-right text-ink-3">
                        {price(row.entry)}
                      </td>
                      <td className="px-3 py-2 text-right text-ink-2">
                        {price(row.mark)}
                      </td>
                      <td className="px-3 py-2 text-right text-ink-2">
                        {usd(row.value)}
                      </td>
                      <td className="px-3 py-2 text-right text-ink-3">
                        {usd(row.high_water_value)}
                      </td>
                      <td className="px-3 py-2 text-right text-down">
                        {usd(row.trail_stop_value)}
                      </td>
                      <td
                        className={`px-3 py-2 text-right ${TONE_CLASS[tone(row.unrealised_usd)]}`}
                      >
                        {signedUsd(row.unrealised_usd)}{" "}
                        <span className="text-ink-4">
                          {pct(row.unrealised_pct)}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right text-ink-3">
                        {fmtHours(row.hours_held)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel density="comfortable">
          <PanelHeader>
            <PanelTitle>Equity</PanelTitle>
            <div className="flex rounded border border-line" role="group"
              aria-label="Equity window">
              {EQUITY_WINDOWS.map((option) => (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => setWindow(option.hours)}
                  aria-pressed={window === option.hours}
                  className={`px-2 py-1 text-label uppercase ${
                    window === option.hours
                      ? "bg-surface-2 text-ink"
                      : "text-ink-4"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </PanelHeader>
          <EquityCurve
            points={equity.data ?? []}
            baseline={STARTING_EQUITY}
            className="h-28 w-full"
          />
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
            <Stat
              label="Return"
              value={pct(tradeStats.data?.return_pct)}
              toneKey={tone(tradeStats.data?.return_pct)}
            />
            <Stat label="Peak" value={usd(account.data?.peak_equity)} />
            <Stat label="Cash" value={usd(account.data?.cash)} />
            <Stat
              label="Max DD"
              value={plainPct(tradeStats.data?.max_drawdown_pct)}
            />
          </div>
        </Panel>
      </div>

      {/* 5 — trades and the two verdict cards */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Panel density="flush">
          <PanelHeader className="px-4 pt-3">
            <PanelTitle>Closed trades</PanelTitle>
            <span className="text-label uppercase text-ink-4">
              {trades.data?.total ?? 0} total
            </span>
          </PanelHeader>
          {(trades.data?.items ?? []).length === 0 ? (
            <EmptyState
              title="No closed trades"
              body="Nothing has been bought and sold yet."
            />
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-label uppercase text-ink-4">
                    <tr className="border-b border-line">
                      <th className="px-4 py-2 text-left">Token</th>
                      <th className="px-3 py-2 text-right">Entry</th>
                      <th className="px-3 py-2 text-right">Exit</th>
                      <th className="px-3 py-2 text-right">P&amp;L</th>
                      <th className="px-4 py-2 text-left">Reason</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono tabular-nums">
                    {(trades.data?.items ?? []).map((row) => (
                      <tr key={row.id} className="border-b border-line/50">
                        <td className="px-4 py-2 text-left text-ink">
                          {row.symbol ?? shortenAddress(row.mint)}
                        </td>
                        <td className="px-3 py-2 text-right text-ink-3">
                          {price(row.entry)}
                        </td>
                        <td className="px-3 py-2 text-right text-ink-3">
                          {price(row.exit)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right ${TONE_CLASS[tone(row.pnl_usd)]}`}
                        >
                          {signedUsd(row.pnl_usd)}{" "}
                          <span className="text-ink-4">{pct(row.pnl_pct)}</span>
                        </td>
                        <td className="px-4 py-2 text-left text-ink-3">
                          {EXIT_LABELS[row.exit_reason] ?? row.exit_reason}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager
                page={tradePage}
                total={trades.data?.total ?? 0}
                onChange={setTradePage}
              />
            </>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel density="comfortable">
            <PanelHeader>
              <PanelTitle>Trading</PanelTitle>
            </PanelHeader>
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Trades" value={String(tradeStats.data?.trades ?? 0)} />
              <Stat label="Win rate" value={rate(tradeStats.data?.win_rate, 1)} />
              <Stat
                label="Expectancy"
                value={plainPct(tradeStats.data?.expectancy_pct, 2)}
                toneKey={tone(tradeStats.data?.expectancy_pct)}
              />
              <Stat
                label="Profit factor"
                value={
                  tradeStats.data?.profit_factor === null ||
                  tradeStats.data?.profit_factor === undefined
                    ? "—"
                    : tradeStats.data.profit_factor.toFixed(2)
                }
              />
              <Stat label="Avg win" value={plainPct(tradeStats.data?.avg_win_pct)} />
              <Stat label="Avg loss" value={plainPct(tradeStats.data?.avg_loss_pct)} />
              <Stat label="Fees" value={usd(tradeStats.data?.fees_total)} />
            </div>
          </Panel>

          {/* The one that answers the actual question. */}
          <Panel density="comfortable">
            <PanelHeader>
              <PanelTitle>Does the score work?</PanelTitle>
            </PanelHeader>
            <p className="mb-3 text-xs text-ink-4">
              Completed episodes by the momentum score they were recorded at,
              against what a $100 position with a $25 trailing stop would have
              returned. If the score predicts anything, the top deciles beat
              the bottom ones.
            </p>
            {(stats.data?.outcomes.n ?? 0) === 0 ? (
              <p className="text-sm text-ink-4">
                No episode has completed its 72-hour window yet.
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead className="text-label uppercase text-ink-4">
                  <tr className="border-b border-line">
                    <th className="py-1 text-left">Decile</th>
                    <th className="py-1 text-right">n</th>
                    <th className="py-1 text-right">Mean</th>
                    <th className="py-1 text-right">Win</th>
                  </tr>
                </thead>
                <tbody className="font-mono tabular-nums">
                  {(stats.data?.outcomes.by_score_decile ?? []).map((row) => (
                    <tr key={row.decile} data-testid="decile-row">
                      <td className="py-1 text-left text-ink-2">
                        {row.decile * 10}–{row.decile * 10 + 9}
                      </td>
                      <td className="py-1 text-right text-ink-3">{row.n}</td>
                      <td
                        className={`py-1 text-right ${TONE_CLASS[tone(row.mean_trail25_pct)]}`}
                      >
                        {plainPct(row.mean_trail25_pct)}
                      </td>
                      <td className="py-1 text-right text-ink-3">
                        {rate(row.win_rate, 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          <Panel density="comfortable">
            <PanelHeader>
              <PanelTitle>Episodes</PanelTitle>
              <span className="text-label uppercase text-ink-4">
                {episodes.data?.total ?? 0} closed
              </span>
            </PanelHeader>
            {(episodes.data?.items ?? []).length === 0 ? (
              <p className="text-sm text-ink-4">No closed episodes yet.</p>
            ) : (
              <>
                <ul className="space-y-1 text-xs">
                  {(episodes.data?.items ?? []).map((row) => (
                    <li
                      key={row.id}
                      data-testid="episode-row"
                      className="flex justify-between gap-2 border-b border-line/50 py-1"
                    >
                      <span className="text-ink-2">
                        {row.symbol ?? shortenAddress(row.mint)}
                      </span>
                      <span className="text-ink-4">
                        {CLOSE_REASON_LABELS[row.close_reason ?? ""] ??
                          row.close_reason}
                      </span>
                      <span
                        className={`font-mono tabular-nums ${TONE_CLASS[tone(row.trail25_result_pct)]}`}
                      >
                        {plainPct(row.trail25_result_pct)}
                      </span>
                    </li>
                  ))}
                </ul>
                <Pager
                  page={episodePage}
                  total={episodes.data?.total ?? 0}
                  onChange={setEpisodePage}
                />
              </>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Pager({
  page,
  total,
  onChange,
}: {
  page: number;
  total: number;
  onChange: (next: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-between px-4 py-2 text-label uppercase text-ink-4">
      <button
        type="button"
        onClick={() => onChange(Math.max(0, page - 1))}
        disabled={page === 0}
        className="rounded border border-line px-2 py-1 disabled:opacity-40"
      >
        Prev
      </button>
      <span>
        {page + 1} / {pages}
      </span>
      <button
        type="button"
        onClick={() => onChange(Math.min(pages - 1, page + 1))}
        disabled={page >= pages - 1}
        className="rounded border border-line px-2 py-1 disabled:opacity-40"
      >
        Next
      </button>
    </div>
  );
}

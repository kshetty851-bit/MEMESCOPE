"use client";

import { useEffect, useMemo, useState } from "react";

import { Label, Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import { EXIT_LABELS } from "./api";
import { EquityCurve } from "./equity-curve";
import {
  dexscreener,
  duration,
  elapsed,
  pct,
  plainPct,
  price,
  signedUsd,
  TONE_CLASS,
  tone,
  usd,
} from "./format";
import {
  useKarthikComparison,
  useRafiqBreaker,
  useRafiqPositions,
  useRafiqStatus,
  useRafiqTrades,
} from "./hooks";
import type { RafiqStrategy } from "./types";

/**
 * RAFIQ LAB
 *
 * Five strategies supplied by a collaborator, each on its own $1,000 paper
 * book, fed by the same token stream as the existing wallet. **This is not
 * the Paper Wallet and it is not real money.** The page says so above the
 * fold rather than in a footnote: a reader who confused them would draw a
 * conclusion about money that does not exist.
 *
 * Every figure is served already computed. Nothing here recomputes an
 * expectancy, a return or a rate — a second implementation would be a second
 * answer, and the first time either changed they would disagree.
 *
 * The comparison column is the existing wallet's own numbers, from its own
 * endpoint. The two ledgers are never joined in the backend; they are put
 * beside each other here, which is the only place it is safe to do it.
 */

const RULE_ROWS: { key: keyof RafiqStrategy; label: string }[] = [
  { key: "take_profit_mult", label: "Take profit" },
  { key: "stop_mult", label: "Stop" },
  { key: "trailing_frac", label: "Trail" },
  { key: "max_hold_hours", label: "Max hold" },
  { key: "entry_threshold", label: "Entry score" },
];

/**
 * The condition the gate refused most often, and its share of all refusals.
 *
 * One reason rather than all seven: the breakdown is a long tail with two
 * entries that can never fire, and the question a reader is actually asking of
 * this cell is "what is this book mostly turning away?". The full counts are
 * on the endpoint for anyone who wants them.
 */
function topRejection(counts: Record<string, number>): string | null {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (total === 0) return null;
  const [reason, n] = Object.entries(counts).reduce((best, entry) =>
    entry[1] > best[1] ? entry : best,
  );
  return `${reason.replace(/_/g, " ")} ${Math.round((100 * n) / total)}%`;
}

/**
 * The mint, in full, linked to its pool.
 *
 * Full and not truncated: the point of putting it on the row is that a reader
 * can check the trade against the market, and a shortened address cannot be
 * copied into anything. It wraps rather than clipping, and the symbol sits
 * above it because that is what a reader scans by.
 */
function Mint({ mint, symbol }: { mint: string; symbol: string | null }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-ink">{symbol ?? "—"}</span>
      <a
        href={dexscreener(mint)}
        target="_blank"
        rel="noopener noreferrer"
        title="Open this pool on DexScreener"
        className="break-all font-mono text-[0.6875rem] leading-tight text-ink-3 underline decoration-line underline-offset-2 transition-colors hover:text-accent focus-visible:text-accent"
      >
        {mint}
      </a>
    </div>
  );
}

/** Elapsed time since the books opened, ticking once a second. */
function RunningFor({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span className="font-mono tabular-nums text-ink-2">{elapsed(since, now)}</span>
  );
}

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

function StrategyCard({
  strategy,
  selected,
  onSelect,
  halted,
  haltReason,
  leading,
}: {
  strategy: RafiqStrategy;
  selected: boolean;
  onSelect: () => void;
  halted: boolean;
  haltReason: string | null;
  leading: boolean;
}) {
  const returnPct =
    (Number(strategy.equity) / Number(strategy.starting_equity) - 1) * 100;

  return (
    <Panel
      density="compact"
      interactive
      className={selected ? "border-accent" : undefined}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className="w-full text-left"
      >
        <div className="flex items-baseline justify-between gap-2">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-sm text-accent">{strategy.code}</span>
            <span className="truncate text-sm text-ink">{strategy.name}</span>
          </div>
          <span className="flex shrink-0 items-center gap-1.5">
            {leading ? (
              <span
                title="Highest equity right now — not a verdict, the sample is tiny"
                className="rounded border border-up px-1.5 py-0.5 text-label uppercase text-up"
              >
                Leading
              </span>
            ) : null}
            {halted ? (
              <span className="rounded bg-raised px-1.5 py-0.5 text-label uppercase text-warn">
                Halted
              </span>
            ) : null}
          </span>
        </div>

        <div className="mt-2 flex items-end justify-between gap-3">
          <div>
            <p className="font-mono text-lg tabular-nums text-ink">
              {usd(strategy.equity)}
            </p>
            <p
              className={`font-mono text-xs tabular-nums ${
                TONE_CLASS[
                  Number.isFinite(returnPct) && returnPct !== 0
                    ? returnPct > 0
                      ? "up"
                      : "down"
                    : "flat"
                ]
              }`}
            >
              {Number.isFinite(returnPct)
                ? `${returnPct >= 0 ? "+" : "−"}${Math.abs(returnPct).toFixed(1)}%`
                : "—"}{" "}
              <span className="text-ink-4">from {usd(strategy.starting_equity)}</span>
            </p>
          </div>
          <EquityCurve
            points={strategy.equity_curve}
            baseline={strategy.starting_equity}
            className="h-8 w-28"
          />
        </div>

        <p className="mt-2 text-xs text-ink-3">
          Already net of{" "}
          <span className="font-mono tabular-nums text-ink-2">
            {usd(strategy.execution_cost_usd)}
          </span>{" "}
          in fees and price impact — this is what a real wallet would hold.
        </p>

        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-2">
          <Stat label="Open" value={String(strategy.open_positions)} />
          <Stat label="Closed" value={String(strategy.closed_trades)} />
          <Stat
            label="Realised"
            value={signedUsd(strategy.realised_pnl)}
            toneKey={tone(strategy.realised_pnl)}
          />
        </div>
      </button>

      {halted && haltReason ? (
        <p className="mt-2 border-t border-line pt-2 text-xs text-warn">{haltReason}</p>
      ) : null}
    </Panel>
  );
}

export function RafiqLabPage() {
  const status = useRafiqStatus();
  const positions = useRafiqPositions();
  const trades = useRafiqTrades();
  const breaker = useRafiqBreaker();
  const karthik = useKarthikComparison();
  const [selected, setSelected] = useState<string | null>(null);

  const halts = useMemo(() => {
    const map = new Map<string, { halted: boolean; reason: string | null }>();
    for (const row of breaker.data ?? []) {
      // Only D and E are GATED by the breaker. The others are evaluated for
      // comparison, so showing them as halted would misreport what happened.
      map.set(row.strategy_code, {
        halted: row.gates_entries && row.halted,
        reason: row.halted_reason,
      });
    }
    return map;
  }, [breaker.data]);

  // The leader is whoever holds the most equity **among books that have
  // actually traded**. A strategy sitting untouched at its starting $1,000
  // outranks every book that has taken a loss, and badging that as leading
  // would reward not playing.
  //
  // Deliberately "leading" and not "winner": a few dozen closed trades is not
  // a result, and the word winner invites a reader to treat it as one.
  const leader = useMemo(() => {
    const traded = (status.data?.strategies ?? []).filter(
      (s) => s.closed_trades > 0,
    );
    if (traded.length === 0) return null;
    return traded.reduce((best, s) =>
      Number(s.equity) > Number(best.equity) ? s : best,
    ).code;
  }, [status.data]);

  const visiblePositions = useMemo(
    () =>
      (positions.data ?? []).filter((p) => !selected || p.strategy_code === selected),
    [positions.data, selected],
  );
  const visibleTrades = useMemo(
    () => (trades.data ?? []).filter((t) => !selected || t.strategy_code === selected),
    [trades.data, selected],
  );

  if (status.isLoading) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (status.isError) {
    return (
      <div className="p-4">
        <ErrorState
          title="Rafiq Lab is unavailable"
          body="The lab's status endpoint did not respond."
          onRetry={() => status.refetch()}
        />
      </div>
    );
  }

  if (!status.data?.running) {
    return (
      <div className="p-4">
        <EmptyState
          title="Rafiq Lab is not running"
          body={
            "RAFIQ_LAB_ENABLED is off, so no strategy has traded and there is " +
            "nothing to report. This is not an empty book — it is a lab that " +
            "has not been started."
          }
        />
      </div>
    );
  }

  const metrics = karthik.data?.metrics ?? null;

  return (
    <div className="space-y-4 p-4">
      <Panel density="compact">
        <PanelHeader className="flex-col items-start gap-1 sm:flex-row sm:items-center sm:gap-4">
          <PanelTitle>Rafiq Lab</PanelTitle>
          <Label>Research simulation — not the Paper Wallet, not real money</Label>
        </PanelHeader>
        <p className="mt-2 text-sm text-ink-3">
          Running for{" "}
          {status.data.strategies[0] ? (
            <RunningFor since={status.data.strategies[0].activated_at} />
          ) : (
            "—"
          )}{" "}
          · every book opened together, so the clock is the same for all five.
        </p>
        <p className="mt-2 max-w-3xl text-sm text-ink-2">
          Five strategies supplied by a collaborator, each on its own{" "}
          {usd(status.data.starting_equity)} book, fed by the same token stream
          as the existing wallet. Every constant is the collaborator&apos;s and
          none has been tuned here. Nothing below is a forecast, and the lab has
          no target: Strategy D bounds how much a bad day can take away, and
          nothing bounds the other direction.
        </p>
      </Panel>

      <div
        role="group"
        aria-label="Filter by strategy"
        className="flex flex-wrap items-center gap-1.5"
      >
        <span className="mr-1 text-label uppercase text-ink-4">Show</span>
        <button
          type="button"
          onClick={() => setSelected(null)}
          aria-pressed={selected === null}
          className={`rounded border px-2.5 py-1 font-mono text-xs transition-colors ${
            selected === null
              ? "border-accent bg-accent-deep/20 text-accent"
              : "border-line text-ink-3 hover:border-line-strong hover:text-ink-2"
          }`}
        >
          All
        </button>
        {status.data.strategies.map((s) => (
          <button
            key={s.code}
            type="button"
            onClick={() => setSelected(selected === s.code ? null : s.code)}
            aria-pressed={selected === s.code}
            title={s.name}
            className={`rounded border px-2.5 py-1 font-mono text-xs transition-colors ${
              selected === s.code
                ? "border-accent bg-accent-deep/20 text-accent"
                : "border-line text-ink-3 hover:border-line-strong hover:text-ink-2"
            }`}
          >
            {s.code}
          </button>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {status.data.strategies.map((s) => {
          const halt = halts.get(s.code);
          return (
            <StrategyCard
              key={s.code}
              strategy={s}
              selected={selected === s.code}
              onSelect={() => setSelected(selected === s.code ? null : s.code)}
              halted={Boolean(halt?.halted)}
              haltReason={halt?.reason ?? null}
              leading={leader === s.code}
            />
          );
        })}
      </div>

      <Panel density="flush">
        <div className="p-3">
          <PanelTitle>Side by side with the Karthik paper wallet</PanelTitle>
          <Label>
            Two independent ledgers, read from two endpoints. Same feed, same
            starting capital, different rules.
          </Label>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="border-y border-line text-label uppercase text-ink-4">
              <tr>
                <th className="p-2 text-left font-medium">Book</th>
                <th className="p-2 text-right font-medium">Start</th>
                <th className="p-2 text-right font-medium">Equity</th>
                <th className="p-2 text-right font-medium">Realised</th>
                <th className="p-2 text-right font-medium">Open</th>
                <th className="p-2 text-right font-medium">Closed</th>
                <th className="p-2 text-right font-medium">Wins</th>
              </tr>
            </thead>
            <tbody>
              {status.data.strategies.map((s) => (
                <tr key={s.code} className="border-b border-line">
                  <td className="p-2 text-ink">
                    <span className="font-mono text-accent">{s.code}</span> {s.name}
                  </td>
                  <td className="p-2 text-right font-mono tabular-nums text-ink-3">
                    {usd(s.starting_equity)}
                  </td>
                  <td className="p-2 text-right font-mono tabular-nums text-ink">
                    {usd(s.equity)}
                  </td>
                  <td
                    className={`p-2 text-right font-mono tabular-nums ${TONE_CLASS[tone(s.realised_pnl)]}`}
                  >
                    {signedUsd(s.realised_pnl)}
                  </td>
                  <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                    {s.open_positions}
                  </td>
                  <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                    {s.closed_trades}
                  </td>
                  <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                    {s.wins}/{s.closed_trades}
                  </td>
                </tr>
              ))}
              <tr className="border-b border-line bg-sunken">
                <td className="p-2 text-ink">
                  <span className="font-mono text-ink-3">—</span> Karthik paper
                  wallet
                </td>
                <td className="p-2 text-right font-mono tabular-nums text-ink-3">
                  {usd(metrics?.starting_capital)}
                </td>
                <td className="p-2 text-right font-mono tabular-nums text-ink">
                  {usd(metrics?.full_equity)}
                </td>
                <td
                  className={`p-2 text-right font-mono tabular-nums ${TONE_CLASS[tone(metrics?.realized_pnl)]}`}
                >
                  {signedUsd(metrics?.realized_pnl)}
                </td>
                <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                  {metrics?.open_positions ?? "—"}
                </td>
                <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                  {metrics?.closed_positions ?? "—"}
                </td>
                <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                  {metrics ? `${metrics.wins}/${metrics.closed_positions}` : "—"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="p-3 text-xs text-ink-3">
          The two books do not cover the same period: each starts when it was
          activated. Read the columns as two records, never as a difference.
        </p>
      </Panel>

      <Panel density="flush">
        <div className="flex items-baseline justify-between gap-2 p-3">
          <PanelTitle>
            Open positions{selected ? ` — ${selected}` : ""}
          </PanelTitle>
          <Label>{visiblePositions.length} open</Label>
        </div>
        {visiblePositions.length === 0 ? (
          <p className="p-3 pt-0 text-sm text-ink-3">Nothing open.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] text-sm">
              <thead className="border-y border-line text-label uppercase text-ink-4">
                <tr>
                  <th className="p-2 text-left font-medium">Strategy</th>
                  <th className="p-2 text-left font-medium">Token</th>
                  <th className="p-2 text-right font-medium">Age</th>
                  <th className="p-2 text-right font-medium">Cost</th>
                  <th className="p-2 text-right font-medium">Mark</th>
                  <th className="p-2 text-right font-medium">Value</th>
                  <th className="p-2 text-right font-medium">Unrealised</th>
                  <th className="p-2 text-right font-medium">Stop</th>
                </tr>
              </thead>
              <tbody>
                {visiblePositions.map((p) => (
                  <tr key={`${p.strategy_code}-${p.mint_address}`} className="border-b border-line">
                    <td className="p-2 align-top font-mono text-accent">
                      {p.strategy_code}
                    </td>
                    <td className="max-w-[18rem] p-2">
                      <Mint mint={p.mint_address} symbol={p.symbol} />
                    </td>
                    <td className="p-2 text-right align-top font-mono tabular-nums text-ink-2">
                      {duration(p.age_seconds)}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                      {usd(p.cost_basis)}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                      {price(p.last_mark_price)}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-ink">
                      {usd(p.current_value)}
                    </td>
                    <td
                      className={`p-2 text-right font-mono tabular-nums ${TONE_CLASS[tone(p.unrealised_pnl)]}`}
                    >
                      {signedUsd(p.unrealised_pnl)}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-ink-3">
                      −{plainPct(p.stop_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel density="flush">
        <div className="flex items-baseline justify-between gap-2 p-3">
          <PanelTitle>Closed trades{selected ? ` — ${selected}` : ""}</PanelTitle>
          <Label>{visibleTrades.length} closed</Label>
        </div>
        {visibleTrades.length === 0 ? (
          <p className="p-3 pt-0 text-sm text-ink-3">Nothing closed yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] text-sm">
              <thead className="border-y border-line text-label uppercase text-ink-4">
                <tr>
                  <th className="p-2 text-left font-medium">Strategy</th>
                  <th className="p-2 text-left font-medium">Token</th>
                  <th className="p-2 text-left font-medium">Exit</th>
                  <th className="p-2 text-right font-medium">Held</th>
                  <th className="p-2 text-right font-medium">Cost</th>
                  <th className="p-2 text-right font-medium">Proceeds</th>
                  <th className="p-2 text-right font-medium">P&amp;L</th>
                  <th className="p-2 text-right font-medium">Return</th>
                  <th
                    className="p-2 text-right font-medium"
                    title="What the position would be worth now had it never been closed"
                  >
                    If held
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleTrades.map((t) => (
                  <tr
                    key={`${t.strategy_code}-${t.mint_address}-${t.closed_at}`}
                    className="border-b border-line"
                  >
                    <td className="p-2 align-top font-mono text-accent">
                      {t.strategy_code}
                    </td>
                    <td className="max-w-[18rem] p-2">
                      <Mint mint={t.mint_address} symbol={t.symbol} />
                    </td>
                    <td className="p-2 text-ink-2" title={t.exit_evidence ?? undefined}>
                      {EXIT_LABELS[t.exit_reason] ?? t.exit_reason}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                      {duration(t.hold_seconds)}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                      {usd(t.cost_basis)}
                    </td>
                    <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                      {usd(t.proceeds_usd)}
                    </td>
                    <td
                      className={`p-2 text-right font-mono tabular-nums ${TONE_CLASS[tone(t.realised_pnl)]}`}
                    >
                      {signedUsd(t.realised_pnl)}
                    </td>
                    <td
                      className={`p-2 text-right align-top font-mono tabular-nums ${TONE_CLASS[tone(t.return_pct)]}`}
                    >
                      {pct(t.return_pct)}
                    </td>
                    <td className="p-2 text-right align-top font-mono tabular-nums">
                      {t.if_held_value === null ? (
                        <span className="text-ink-4" title="Nothing prices this mint any more — not the same as zero">
                          —
                        </span>
                      ) : (
                        <>
                          <span className="text-ink-2">{usd(t.if_held_value)}</span>{" "}
                          <span className={TONE_CLASS[tone(t.if_held_pct)]}>
                            {pct(t.if_held_pct)}
                          </span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel density="flush">
        <div className="p-3">
          <PanelTitle>Daily breaker</PanelTitle>
          <Label>
            Gates entries for D and E only. Shown for the rest so a reader can
            see what it would have done to them.
          </Label>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <thead className="border-y border-line text-label uppercase text-ink-4">
              <tr>
                <th className="p-2 text-left font-medium">Strategy</th>
                <th className="p-2 text-left font-medium">Day</th>
                <th className="p-2 text-right font-medium">Open equity</th>
                <th className="p-2 text-right font-medium">Realised today</th>
                <th className="p-2 text-left font-medium">State</th>
              </tr>
            </thead>
            <tbody>
              {(breaker.data ?? []).map((b) => (
                <tr key={b.strategy_code} className="border-b border-line">
                  <td className="p-2 font-mono text-accent">{b.strategy_code}</td>
                  <td className="p-2 font-mono tabular-nums text-ink-2">{b.day}</td>
                  <td className="p-2 text-right font-mono tabular-nums text-ink-2">
                    {usd(b.day_open_equity)}
                  </td>
                  <td
                    className={`p-2 text-right font-mono tabular-nums ${TONE_CLASS[tone(b.realised_today)]}`}
                  >
                    {signedUsd(b.realised_today)}
                  </td>
                  <td className="p-2 text-ink-2">
                    {b.halted ? (
                      <span className={b.gates_entries ? "text-warn" : "text-ink-3"}>
                        {b.gates_entries ? "Halted — no new entries" : "Would halt"}
                        {b.halted_reason ? ` · ${b.halted_reason}` : ""}
                      </span>
                    ) : (
                      "Running"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="p-3 text-xs text-ink-3">
          A halt stops new entries only. Open positions keep running under their
          own exit rules — the lab never force-closes.
        </p>
      </Panel>

      <Panel density="compact">
        <PanelTitle>The rules, as supplied</PanelTitle>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="border-y border-line text-label uppercase text-ink-4">
              <tr>
                <th className="p-2 text-left font-medium">Rule</th>
                {status.data.strategies.map((s) => (
                  <th key={s.code} className="p-2 text-right font-mono font-medium text-accent">
                    {s.code}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {RULE_ROWS.map((row) => (
                <tr key={row.key} className="border-b border-line">
                  <td className="p-2 text-ink-2">{row.label}</td>
                  {status.data.strategies.map((s) => (
                    <td
                      key={s.code}
                      className="p-2 text-right font-mono tabular-nums text-ink"
                    >
                      {s[row.key] === null ? "—" : String(s[row.key])}
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="border-b border-line">
                <td className="p-2 text-ink-2">Stop from liquidity</td>
                {status.data.strategies.map((s) => (
                  <td key={s.code} className="p-2 text-right text-ink">
                    {s.liquidity_derived_risk ? "yes" : "—"}
                  </td>
                ))}
              </tr>
              <tr className="border-b border-line">
                <td className="p-2 text-ink-2">Daily breaker</td>
                {status.data.strategies.map((s) => (
                  <td key={s.code} className="p-2 text-right text-ink">
                    {s.daily_breaker ? "yes" : "—"}
                  </td>
                ))}
              </tr>
              <tr className="border-b border-line">
                <td className="p-2 text-ink-2">Consensus gate</td>
                {status.data.strategies.map((s) => (
                  <td key={s.code} className="p-2 text-right text-ink">
                    {s.consensus_gate ? "yes" : "—"}
                  </td>
                ))}
              </tr>
              <tr className="border-b border-line">
                <td className="p-2 text-ink-2">Entry gate</td>
                {status.data.strategies.map((s) => (
                  <td
                    key={s.code}
                    className="p-2 text-right font-mono tabular-nums text-ink"
                  >
                    {usd(s.gate.min_liquidity_usd, 0)} liq
                    <span className="block text-ink-3">
                      {usd(s.gate.min_market_cap_usd, 0)} cap ·{" "}
                      {s.gate.max_entry_price_impact_pct}% impact
                    </span>
                  </td>
                ))}
              </tr>
              <tr className="border-b border-line">
                <td className="p-2 text-ink-2">
                  Rejected by gate
                  <span className="block text-ink-3">
                    cumulative, since activation
                  </span>
                </td>
                {status.data.strategies.map((s) => (
                  <td
                    key={s.code}
                    className="p-2 text-right font-mono tabular-nums text-ink"
                  >
                    {s.entries_rejected_by_gate.toLocaleString()}
                    <span className="block text-ink-3">
                      {topRejection(s.rejection_reason_counts) ?? "—"}
                    </span>
                  </td>
                ))}
              </tr>
              {/* Gross beside net is the pair that turned "everything loses"
                  into "B is nearly breakeven and dying to friction". Shown
                  together, never apart, because either alone misleads. */}
              <tr className="border-b border-line">
                <td className="p-2 text-ink-2">Realised, gross of costs</td>
                {status.data.strategies.map((s) => (
                  <td
                    key={s.code}
                    className={`p-2 text-right font-mono tabular-nums ${
                      TONE_CLASS[tone(s.gross_pnl_ex_fees)]
                    }`}
                  >
                    {signedUsd(s.gross_pnl_ex_fees)}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="p-2 text-ink-2">Mean per trade, net</td>
                {status.data.strategies.map((s) => (
                  <td
                    key={s.code}
                    className={`p-2 text-right font-mono tabular-nums ${
                      TONE_CLASS[tone(s.mean_pnl_per_trade_net)]
                    }`}
                  >
                    {s.mean_pnl_per_trade_net === null
                      ? "—"
                      : signedUsd(s.mean_pnl_per_trade_net)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

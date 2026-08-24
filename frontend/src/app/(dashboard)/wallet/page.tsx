"use client";

import { useMemo, useState } from "react";

import { AuditLog } from "@/components/paper/audit-log";
import { EntriesPausedBanner } from "@/components/paper/entries-paused-banner";
import { DailyReturns } from "@/components/paper/daily-returns";
import { PositionsTable } from "@/components/paper/positions-table";
import { StrategyCard } from "@/components/paper/strategy-card";
import { WalletSwitch } from "@/components/paper/wallet-switch";
import { Label, Panel } from "@/components/ui/panel";
import { Stat as SharedStat } from "@/components/ui/stat";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import {
  useManualSell,
  useManualSellPreview,
  usePaperAudit,
  usePaperPerformance,
  usePaperPositions,
  usePaperWallet,
  usePaperWalletContext,
} from "@/hooks/use-paper";
import { formatAge } from "@/lib/format";
import { hours, pct, tone, usd } from "@/lib/paper";
import { cn } from "@/lib/utils";

/**
 * THE PAPER WALLET
 *
 * A deterministic simulation of one published rule over prices this platform
 * already stored. No wallet is connected, no order is placed, no chain is
 * touched, and nothing on this page is advice.
 *
 * The page is built to be able to report a **loss**, prominently. A paper
 * wallet that could only look good would be marketing; the reason to build one
 * is to find out whether the Radar's ranking survives a mechanical rule, and
 * "it did not" is a result worth showing at the same size as "it did".
 *
 * Every figure is derived from the positions. Where no trade supports a number
 * it renders "—", never zero: "we have not measured this" and "this is zero"
 * are different claims.
 *
 * **There is no strategy selector and no manual entry.** One rule opens
 * positions. A manual paper exit is recorded separately as an override, never
 * as evidence that the automated rule chose that close.
 */

type Tab = "open" | "closed";

/**
 * Local name, shared implementation.
 *
 * The visual used to be declared here, in `record` and in
 * `record` — near-identical blocks that disagreed about
 * value size, border treatment and dash handling. This keeps the call sites
 * (there are ~25 in this file) and delegates the rendering, so there is now
 * exactly one implementation of a label-over-value in the product.
 */
function Stat({
  label,
  value,
  hint,
  emphasis,
  valueTone,
}: {
  label: string;
  value: string | null;
  hint?: string;
  emphasis?: boolean;
  valueTone?: "positive" | "negative" | "neutral";
}) {
  return (
    <SharedStat
      label={label}
      // Display-only: `usd()`/`pct()` already formatted this, and the raw
      // Decimal is not kept. `Num` takes presence from `display`.
      display={value}
      hint={hint}
      size={emphasis ? "lg" : "md"}
      tone={valueTone === "positive" ? "up" : valueTone === "negative" ? "down" : "default"}
    />
  );
}

export default function WalletPage() {
  const wallet = usePaperWallet();
  const context = usePaperWalletContext(wallet.data?.metrics?.roi_pct);
  const positions = usePaperPositions();
  const auditQuery = usePaperAudit();
  const performanceQuery = usePaperPerformance();
  const manualPreview = useManualSellPreview();
  const manualSell = useManualSell();
  const [tab, setTab] = useState<Tab>("open");

  const items = useMemo(() => {
    if (!positions.data) return [];
    return positions.data.items ?? [];
  }, [positions.data]);

  const visible = useMemo(
    () =>
      items.filter((item) =>
        tab === "open" ? item.status === "open" : item.status === "closed",
      ),
    [items, tab],
  );

  if (wallet.isError) {
    return (
      <ErrorState
        body="The paper wallet is not responding. Positions already recorded are safe — this view will recover on its own."
        onRetry={() => void wallet.refetch()}
      />
    );
  }

  if (wallet.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 rounded-md" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-20 rounded-md" />
          ))}
        </div>
      </div>
    );
  }

  const { strategy, disclosure, last_trade: last, lineage } = wallet.data;
  const m = wallet.data.metrics;
  const waiting = context.data?.waiting;
  const benchmarks = context.data?.benchmarks;

  if (!wallet.data.enabled) {
    return (
      <div className="flex flex-col gap-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <Label>Paper wallet</Label>
            <h1 className="mt-2 text-lg font-semibold text-ink">Not running here</h1>
          </div>
          <WalletSwitch />
        </header>
        <Panel density="compact" className="border-warn/20 bg-warn/[0.03]">
          <p className="text-sm leading-relaxed text-ink-2">
            The paper wallet is not switched on in this environment, so no position has been
            opened. This is a configuration state, not a result — a strategy that traded
            nothing and a strategy that was never run are different things, and this is the
            second.
          </p>
        </Panel>
        <StrategyCard strategy={strategy} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Paper wallet</Label>
          <h1 className="mt-2 text-lg font-semibold text-ink">
            {strategy.name} —{" "}
            {wallet.data.resumed_at ? "resumed paper strategy" : "forward paper strategy"}
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-2">{disclosure}</p>
        </div>
        {/* When the wallet started is not decoration: every benchmark below is
            measured from this exact instant, so a reader can check that the
            comparison covers the same period the strategy traded. */}
        {/* Two paper experiments now run side by side, on separate capital and
            separate tables. The switch is here rather than in the rail because
            it chooses *which wallet you are reading*, not which section of the
            product you are in — and because nothing about this wallet's figures
            changes when it is used. */}
        <div className="flex flex-col items-end gap-2">
          <WalletSwitch />
          {wallet.data.started_at ? (
            <p className="text-xs text-ink-3">
              Running since {new Date(wallet.data.started_at).toLocaleString()} · wallet v
              {wallet.data.generation}
            </p>
          ) : null}
        </div>
      </header>

      {wallet.data.entries_paused ? (
        <EntriesPausedBanner reason={wallet.data.pause_reason} />
      ) : null}

      {wallet.data.resumed_at ? (
        <Panel density="compact" className="border-line-strong bg-raised/40">
          <p className="text-sm text-ink">
            Generation 2 resumed on {new Date(wallet.data.resumed_at).toLocaleString()}
          </p>
        </Panel>
      ) : null}

      {/* Which generation is trading, and whose money it is trading with.
          These are two different facts and the page used to show only the
          first: capital is inherited at a cutover rather than minted, so the
          figures below belong to the whole lineage while only the newest
          generation takes entries. A reader seeing "$1 available" on a
          generation with no trades has to be able to see where it went. */}
      {lineage ? (
        <Panel density="compact" className="border-line-strong bg-raised/40">
          <p className="text-sm text-ink">
            Active generation: Gen {wallet.data.generation} ·{" "}
            <span className="font-mono text-xs">{strategy.id}</span>
          </p>
          <p className="mt-1 text-xs text-ink-3">
            {lineage.generations.length > 1
              ? `Capital below is the shared lineage — generations ${lineage.generations
                  .map((generation) => `${generation}`)
                  .join(", ")} — funded once with ${usd(lineage.base_capital)} by Gen ${
                  lineage.base_generation
                }. Positions and the Track Record stay generation-specific.`
              : `Funded with ${usd(lineage.base_capital)}. This generation shares capital with no other.`}
          </p>
        </Panel>
      ) : null}

      {/* Why the wallet is idle, whenever it is. Two different states and the
          page names which — a wallet sitting on cash with no explanation reads
          as broken, which is exactly how it read before this existed. The
          message comes from the server off a stable `reason` code; nothing here
          composes prose from a slug. */}
      {context.isPending ? (
        <Skeleton className="h-24 w-full rounded-md" />
      ) : waiting ? (
        <Panel density="compact" className="border-line-strong bg-raised/40">
          <p className="text-sm text-ink">{waiting.message}</p>
          {waiting.reason === "cash_below_trade_size" ? (
            <p className="mt-1 text-xs text-ink-3">
              {usd(waiting.idle_cash)} uninvested against a {usd(waiting.trade_size)}{" "}
              position — {usd(waiting.shortfall)} short.{" "}
              {waiting.eligible > 0
                ? `${waiting.eligible} Radar token${waiting.eligible === 1 ? "" : "s"} would qualify if the cash were there.`
                : "Nothing on the Radar qualifies right now either."}
            </p>
          ) : (
            <>
              <p className="mt-1 text-xs text-ink-3">
                {usd(waiting.idle_cash)} uninvested. {waiting.considered} Radar token
                {waiting.considered === 1 ? "" : "s"} considered on the last pass.
              </p>
              <ul className="mt-2 flex flex-col gap-1">
                {Object.entries(waiting.refusals).map(([code, count]) => (
                  <li key={code} className="text-xs text-ink-3">
                    {count} · {waiting.labels[code] ?? code}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Panel>
      ) : null}

      {/* Full equity stays strict: a missing quote never becomes a fabricated
          zero. The partial figure makes the known portion visible alongside it. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <Stat
          label="Current return"
          value={
            m.return_usd === null || m.roi_pct === null
              ? "Pending fresh quotes"
              : `${usd(m.return_usd) ?? "—"} (${pct(m.roi_pct) ?? "—"})`
          }
          emphasis
          valueTone={tone(m.return_usd)}
          hint={
            m.return_usd === null
              ? "Full return appears once every open holding has a fresh stored price."
              : `Marked against ${usd(m.starting_balance)} lineage capital`
          }
        />
        <Stat
          label="Available cash"
          value={usd(m.cash)}
          emphasis
          hint={
            lineage && lineage.generations.length > 1
              ? "Available for the next allocation, across the whole lineage"
              : "Available for the next allocation"
          }
        />
        <Stat
          label="Known partial equity"
          value={usd(m.known_partial_equity)}
          emphasis
          hint={`Cash + ${m.priced_positions} currently priced holding${m.priced_positions === 1 ? "" : "s"}`}
        />
        <Stat
          label="Full equity"
          value={m.equity === null ? "Pending fresh quotes" : usd(m.equity)}
          hint={
            m.equity === null
              ? "Full equity will appear once all resumed holdings receive fresh post-resume market quotes."
              : `from ${usd(m.starting_balance)} lineage base`
          }
        />
        <Stat
          label="Unpriced positions"
          value={`${m.unpriced_positions} of ${m.open_positions}`}
          hint={`${m.priced_positions} priced position${m.priced_positions === 1 ? "" : "s"}`}
        />
        <Stat
          label="Capital in open positions"
          value={usd(m.invested_usd)}
          hint={
            lineage && lineage.generations.length > 1
              ? `Allocation basis across ${m.open_positions} position${m.open_positions === 1 ? "" : "s"} in the lineage, not current market value`
              : "Allocation basis, not current market value"
          }
        />
      </div>

      <Panel density="compact" className="border-line-strong bg-raised/40">
        <p className="text-sm text-ink">Next entry requires $100 available cash</p>
        <p className="mt-1 text-xs text-ink-3">Current available: {usd(m.cash)}</p>
      </Panel>

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-md font-medium text-ink">
            Strategy returns
            {lineage && lineage.generations.length > 1
              ? ` — Gen ${wallet.data.generation}`
              : null}
          </h2>
          <p className="mt-1 text-sm text-ink-2">
            Current return includes every fully priced open holding. Daily rows show
            completed trades by their recorded UTC exit date.
            {lineage && lineage.generations.length > 1
              ? " These rows are this generation's own trades; the capital above and the record below cover the whole lineage."
              : null}
          </p>
        </div>
        <DailyReturns
          daily={performanceQuery.data?.daily ?? []}
          disclosure={performanceQuery.data?.disclosure ?? ""}
          isPending={performanceQuery.isPending}
          isError={performanceQuery.isError}
        />
      </section>

      {/* Lineage-wide, like the capital above: these describe the money's
          whole history, not the newest generation's slice of it. Said out loud
          because the daily rows immediately above are generation-scoped, and a
          reader has no way to tell two adjacent blocks apart otherwise. */}
      {lineage && lineage.generations.length > 1 ? (
        <p className="text-xs text-ink-3">
          Trade record across the whole lineage — generations{" "}
          {lineage.generations.join(", ")}.
        </p>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Win rate" value={pct(m.win_rate_pct)} />
        <Stat
          label="Realised P/L"
          value={usd(m.realised_pnl)}
          valueTone={tone(m.realised_pnl)}
        />
        <Stat label="Average win" value={usd(m.average_win)} valueTone="positive" />
        <Stat label="Average loss" value={usd(m.average_loss)} valueTone="negative" />
        <Stat label="Largest winner" value={usd(m.largest_winner)} valueTone="positive" />
        <Stat label="Largest loser" value={usd(m.largest_loser)} valueTone="negative" />
        <Stat
          label="Max drawdown"
          value={pct(m.max_drawdown_pct)}
          hint="Realised curve only"
        />
        <Stat label="Average hold" value={hours(m.average_hold_hours)} />
      </div>

      {/* The drawdown figure states its own limit rather than implying it is
          the intraday number. */}
      <p className="text-xs leading-relaxed text-ink-3">{m.max_drawdown_note}</p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Stat
          label="Current strategy"
          value={`${strategy.name} v${strategy.version}`}
          hint="The only strategy that runs. There is no selector."
        />
        {/* Opens count as trades, not only closes. A wallet that deployed its
            last dollar an hour ago acted; showing only exits would read as idle
            on a fully-invested book. */}
        <Stat
          label="Last trade"
          value={
            last
              ? `${last.action === "closed" ? "Closed" : "Opened"} ${last.symbol ?? `${last.mint_address.slice(0, 4)}…`}`
              : null
          }
          hint={
            last
              ? `${formatAge(last.at)} ago`
              : lineage && lineage.generations.length > 1
                ? `Gen ${wallet.data.generation} has not traded yet`
                : "Nothing has traded yet"
          }
        />
        <Stat
          label="Next Radar evaluation"
          value={
            wallet.data.next_radar_evaluation_at
              ? new Date(wallet.data.next_radar_evaluation_at).toLocaleTimeString()
              : null
          }
          hint="Exits do not wait for it — they resolve from stored readings."
        />
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-md font-medium text-ink">Measured against</h2>
        {context.isPending ? (
          <div className="flex flex-col gap-3 sm:flex-row">
            <Skeleton className="h-24 w-full rounded-md sm:w-1/2" />
            <Skeleton className="h-24 w-full rounded-md sm:w-1/2" />
          </div>
        ) : benchmarks ? (
          <>
            {context.data?.benchmark_note ? (
              <p className="text-xs leading-relaxed text-ink-3">{context.data.benchmark_note}</p>
            ) : null}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b border-line text-label uppercase tracking-wide text-ink-3">
                    <th className="py-2 text-left font-medium">Benchmark</th>
                    <th className="py-2 text-right font-medium">Held</th>
                    <th className="py-2 text-right font-medium">Benchmark return</th>
                    <th className="py-2 text-right font-medium">This strategy</th>
                    <th className="py-2 text-right font-medium">Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {benchmarks.map((benchmark) => (
                <tr key={benchmark.id} className="border-b border-line/50 align-top">
                  <td className="py-3 pr-4">
                    <p className="text-ink">{benchmark.label}</p>
                    <p className="mt-0.5 text-xs text-ink-3">{benchmark.description}</p>
                    {benchmark.unavailable_reason ? (
                      <p className="mt-1 text-xs text-ink-3">
                        {benchmark.unavailable_reason}
                      </p>
                    ) : null}
                  </td>
                  {/* Unpriceable constituents are shown rather than dropped:
                      excluding them would hand the benchmark a survivorship
                      advantage the wallet never had. */}
                  <td className="py-3 text-right tabular-nums text-ink-3">
                    {benchmark.positions > 0 || benchmark.unpriced > 0
                      ? `${benchmark.positions}${benchmark.unpriced > 0 ? ` (+${benchmark.unpriced} unpriced)` : ""}`
                      : "—"}
                  </td>
                  <td className="py-3 text-right tabular-nums text-ink-2">
                    {pct(benchmark.return_pct) ?? "—"}
                  </td>
                  <td className="py-3 text-right tabular-nums text-ink-2">
                    {pct(m.roi_pct) ?? "—"}
                  </td>
                  <td
                    className={cn(
                      "py-3 text-right tabular-nums",
                      tone(benchmark.difference_pct) === "positive" && "text-up",
                      tone(benchmark.difference_pct) === "negative" && "text-down",
                      tone(benchmark.difference_pct) === "neutral" && "text-ink-3",
                    )}
                  >
                    {pct(benchmark.difference_pct) ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>

      <StrategyCard strategy={strategy} />

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-1">
          {(["open", "closed"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              aria-pressed={tab === key}
              className={cn(
                "rounded-sm border px-2.5 py-1 text-xs capitalize transition-colors",
                tab === key
                  ? "border-line-strong bg-raised text-ink"
                  : "border-line text-ink-3 hover:border-line-strong hover:text-ink",
              )}
            >
              {key} ({key === "open" ? m.open_positions : m.closed_positions})
            </button>
          ))}
        </div>
        <PositionsTable
          positions={visible}
          isPending={positions.isPending}
          onPreviewManualSell={(mint) => manualPreview.mutateAsync(mint)}
          onManualSell={(mint) => manualSell.mutateAsync(mint)}
          emptyLabel={
            tab === "open"
              ? "No position is open. The strategy buys the highest-ranked eligible token on the Radar whenever cash allows."
              : "Nothing has closed yet. A position closes only when the price gives back a quarter of its highest level."
          }
        />
        {tab === "closed" ? (
          <p className="text-xs leading-relaxed text-ink-3">
            Gross P/L is the price result before costs. Net P/L deducts the recorded fees
            and slippage; a dash means the historic trade could not be costed completely.
          </p>
        ) : null}
      </section>

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-md font-medium text-ink">Permanent record</h2>
          <p className="mt-1 text-sm text-ink-2">
            {wallet.data.audited_trades} completed trade
            {wallet.data.audited_trades === 1 ? "" : "s"}, each written once at the moment
            it closed. Nothing in this record is ever rewritten.
          </p>
        </div>
        <AuditLog
          items={auditQuery.data?.items ?? []}
          total={auditQuery.data?.total ?? 0}
          disclosure={auditQuery.data?.disclosure ?? ""}
          isPending={auditQuery.isPending}
        />
      </section>
    </div>
  );
}

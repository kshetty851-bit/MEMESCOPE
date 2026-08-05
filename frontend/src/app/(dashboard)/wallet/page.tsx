"use client";

import { useMemo, useState } from "react";

import { AuditLog } from "@/components/paper/audit-log";
import { PositionsTable } from "@/components/paper/positions-table";
import { StrategyCard } from "@/components/paper/strategy-card";
import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { usePaperAudit, usePaperPositions, usePaperWallet } from "@/hooks/use-paper";
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
 * **There is no strategy selector, and there is no button.** One rule runs;
 * choosing between rules after seeing their results would be the hindsight the
 * whole design exists to prevent, and a manual entry would make this a record
 * of judgement rather than of a rule.
 */

type Tab = "open" | "closed";

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
    <div className="rounded-card border border-line bg-surface/40 px-4 py-3">
      <p className="text-label uppercase tracking-wide text-ink-faint">{label}</p>
      <p
        className={cn(
          "mt-1 tabular-nums",
          emphasis ? "text-2xl font-semibold" : "text-lg",
          value === null && "text-ink-faint",
          valueTone === "positive" && "text-safe",
          valueTone === "negative" && "text-danger",
          !valueTone && value !== null && "text-ink",
        )}
      >
        {value ?? "—"}
      </p>
      {hint ? <p className="mt-1 text-xs text-ink-faint">{hint}</p> : null}
    </div>
  );
}

export default function WalletPage() {
  const wallet = usePaperWallet();
  const positions = usePaperPositions();
  const auditQuery = usePaperAudit();
  const [tab, setTab] = useState<Tab>("open");

  const items = useMemo(() => positions.data?.items ?? [], [positions.data]);
  const visible = useMemo(
    () => items.filter((item) => (tab === "open" ? item.status === "open" : item.status === "closed")),
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
        <Skeleton className="h-24 rounded-card" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-20 rounded-card" />
          ))}
        </div>
      </div>
    );
  }

  const { metrics: m, strategy, benchmarks, disclosure, waiting, last_trade: last } = wallet.data;

  if (!wallet.data.enabled) {
    return (
      <div className="flex flex-col gap-6">
        <header>
          <Label>Paper wallet</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">Not running here</h1>
        </header>
        <Panel density="compact" className="border-warn/20 bg-warn/[0.03]">
          <p className="text-sm leading-relaxed text-ink-dim">
            The paper wallet is not switched on in this environment, so no position
            has been opened. This is a configuration state, not a result — a
            strategy that traded nothing and a strategy that was never run are
            different things, and this is the second.
          </p>
        </Panel>
        <StrategyCard strategy={strategy} />
      </div>
    );
  }

  const roiTone = tone(m.roi_pct);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Paper wallet</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            One published rule, applied without exception
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-dim">{disclosure}</p>
        </div>
        {/* When the wallet started is not decoration: every benchmark below is
            measured from this exact instant, so a reader can check that the
            comparison covers the same period the strategy traded. */}
        {wallet.data.started_at ? (
          <p className="text-xs text-ink-faint">
            Running since {new Date(wallet.data.started_at).toLocaleString()} · wallet
            v{wallet.data.generation}
          </p>
        ) : null}
      </header>

      {/* Sprint 30 §9. Published only while it is true: enough cash for a full
          position and nothing on the Radar qualifying. The wallet never buys a
          lower-quality token to avoid an empty screen, so it says so instead. */}
      {waiting ? (
        <Panel density="compact" className="border-line-bright bg-elevated/40">
          <p className="text-sm text-ink">{waiting.message}</p>
          <p className="mt-1 text-xs text-ink-faint">
            {usd(waiting.idle_cash)} uninvested. {waiting.considered} Radar token
            {waiting.considered === 1 ? "" : "s"} considered on the last pass.
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {Object.entries(waiting.refusals).map(([code, count]) => (
              <li key={code} className="text-xs text-ink-faint">
                {count} · {waiting.labels[code] ?? code}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {/* The headline four. ROI is given the same prominence whether it is
          positive or negative — a wallet that only reported wins would be
          marketing rather than evidence. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Equity"
          value={usd(m.equity)}
          emphasis
          hint={
            m.unpriced_positions > 0
              ? `${m.unpriced_positions} holding${m.unpriced_positions === 1 ? "" : "s"} unpriced`
              : `from ${usd(m.starting_balance)} start`
          }
        />
        <Stat label="Return" value={pct(m.roi_pct)} emphasis valueTone={roiTone} />
        <Stat label="Cash" value={usd(m.cash)} hint={`${usd(m.open_value)} at market`} />
        {/* Invested is what the open positions **cost**, not what they are
            worth. It survives a token going unpriced, where the market value
            does not. */}
        <Stat
          label="Invested"
          value={usd(m.invested_usd)}
          hint={`${m.open_positions} open · ${m.closed_positions} closed`}
        />
      </div>

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
      <p className="text-xs leading-relaxed text-ink-faint">{m.max_drawdown_note}</p>

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
          hint={last ? `${formatAge(last.at)} ago` : "Nothing has traded yet"}
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
        <h2 className="text-heading font-medium text-ink">Measured against</h2>
        {/* Both comparisons start with the same capital at the same instant as
            the wallet. A benchmark drawn over a period the strategy did not
            trade would credit or punish it for free. */}
        {wallet.data.benchmark_note ? (
          <p className="text-xs leading-relaxed text-ink-faint">
            {wallet.data.benchmark_note}
          </p>
        ) : null}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-line text-label uppercase tracking-wide text-ink-faint">
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
                    <p className="mt-0.5 text-xs text-ink-faint">{benchmark.description}</p>
                    {benchmark.unavailable_reason ? (
                      <p className="mt-1 text-xs text-ink-faint">
                        {benchmark.unavailable_reason}
                      </p>
                    ) : null}
                  </td>
                  {/* Unpriceable constituents are shown rather than dropped:
                      excluding them would hand the benchmark a survivorship
                      advantage the wallet never had. */}
                  <td className="py-3 text-right tabular-nums text-ink-faint">
                    {benchmark.positions > 0 || benchmark.unpriced > 0
                      ? `${benchmark.positions}${benchmark.unpriced > 0 ? ` (+${benchmark.unpriced} unpriced)` : ""}`
                      : "—"}
                  </td>
                  <td className="py-3 text-right tabular-nums text-ink-dim">
                    {pct(benchmark.return_pct) ?? "—"}
                  </td>
                  <td className="py-3 text-right tabular-nums text-ink-dim">
                    {pct(m.roi_pct) ?? "—"}
                  </td>
                  <td
                    className={cn(
                      "py-3 text-right tabular-nums",
                      tone(benchmark.difference_pct) === "positive" && "text-safe",
                      tone(benchmark.difference_pct) === "negative" && "text-danger",
                      tone(benchmark.difference_pct) === "neutral" && "text-ink-faint",
                    )}
                  >
                    {pct(benchmark.difference_pct) ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
                "rounded-chip border px-2.5 py-1 text-xs capitalize transition-colors",
                tab === key
                  ? "border-line-bright bg-elevated text-ink"
                  : "border-line text-ink-faint hover:border-line-bright hover:text-ink",
              )}
            >
              {key} ({key === "open" ? m.open_positions : m.closed_positions})
            </button>
          ))}
        </div>
        <PositionsTable
          positions={visible}
          isPending={positions.isPending}
          emptyLabel={
            tab === "open"
              ? "No position is open. The strategy buys the highest-ranked eligible token on the Radar whenever cash allows."
              : "Nothing has closed yet. A position closes only when the price gives back a quarter of its highest level."
          }
        />
      </section>

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-heading font-medium text-ink">Permanent record</h2>
          <p className="mt-1 text-sm text-ink-dim">
            {wallet.data.audited_trades} completed trade
            {wallet.data.audited_trades === 1 ? "" : "s"}, each written once at the
            moment it closed. Nothing in this record is ever rewritten.
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

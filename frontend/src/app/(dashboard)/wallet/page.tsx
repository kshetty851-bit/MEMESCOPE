"use client";

import { useMemo, useState } from "react";

import { PositionsTable } from "@/components/paper/positions-table";
import { StrategyCard } from "@/components/paper/strategy-card";
import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { usePaperPositions, usePaperWallet } from "@/hooks/use-paper";
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

  const { metrics: m, strategy, benchmarks, disclosure } = wallet.data;

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
      </header>

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
        <Stat label="Cash" value={usd(m.cash)} hint={`${usd(m.open_value)} in positions`} />
        <Stat
          label="Realised P/L"
          value={usd(m.realised_pnl)}
          valueTone={tone(m.realised_pnl)}
          hint={`${m.closed_positions} closed · ${m.open_positions} open`}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Win rate" value={pct(m.win_rate_pct)} />
        <Stat
          label="Profit factor"
          value={m.profit_factor}
          hint={m.profit_factor === null ? "Nothing has lost yet" : "Gross profit ÷ gross loss"}
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

      <section className="flex flex-col gap-3">
        <h2 className="text-heading font-medium text-ink">Measured against</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-line text-label uppercase tracking-wide text-ink-faint">
                <th className="py-2 text-left font-medium">Benchmark</th>
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
              ? "No position is open. The strategy enters only when a token first reaches the Radar's top ten."
              : "Nothing has closed yet. Positions close at the target, the stop, or the end of the holding period."
          }
        />
      </section>
    </div>
  );
}

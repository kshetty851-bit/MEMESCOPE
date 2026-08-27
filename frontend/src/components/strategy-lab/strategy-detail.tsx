"use client";

import { useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Tabs } from "@/components/ui/tabs";
import { useLabStrategyDetail } from "@/hooks/use-strategy-lab";
import {
  FILL_REASON_LABEL,
  multiple,
  plain,
  shortMint,
  usd,
  type LabMode,
  type LabTrade,
} from "@/lib/strategy-lab";
import { cn } from "@/lib/utils";

import {
  DatasetFooter,
  FlagChips,
  Money,
  Percent,
  SimulatedBadge,
  StatTile,
} from "./shared";

/**
 * ONE STRATEGY, IN FULL — §13.
 *
 * Equity curve, drawdown, daily P&L, trade distribution, and every trade's
 * complete lifecycle down to the individual fills and their execution prices.
 *
 * The curve is drawn as an inline SVG rather than pulled from a charting
 * library: two polylines over a few hundred points is less code than the
 * import, and it renders in both themes without configuration.
 */

type TradeTab = "best" | "worst" | "recent" | "blocked";

function EquityCurve({
  points,
  start,
}: {
  points: { at: string; equity: number }[];
  start: number;
}) {
  if (points.length < 2) {
    return (
      <p className="px-4 py-8 text-center text-sm text-ink-3">
        Not enough samples to draw a curve.
      </p>
    );
  }

  const width = 1000;
  const height = 220;
  const values = points.map((p) => p.equity);
  const min = Math.min(...values, start);
  const max = Math.max(...values, start);
  const span = max - min || 1;

  const first = points[0]!;
  const last = points[points.length - 1]!;
  const x = (index: number) => (index / (points.length - 1)) * width;
  const y = (value: number) => height - ((value - min) / span) * height;

  const equityPath = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.equity)}`).join(" ");

  // Drawdown, as a running peak-to-current band under the curve. Drawn from
  // the same points so the two can never disagree.
  let peak = start;
  const drawdown = points.map((p) => {
    peak = Math.max(peak, p.equity);
    return peak > 0 ? ((peak - p.equity) / peak) * 100 : 0;
  });
  const worst = Math.max(...drawdown, 1);
  const ddPath = drawdown
    .map((d, i) => `${i === 0 ? "M" : "L"}${x(i)},${height - (d / worst) * height * 0.35}`)
    .join(" ");

  return (
    <div className="space-y-1 px-4 pb-4">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-56 w-full"
        role="img"
        aria-label={`Simulated equity from ${usd(start)} to ${usd(last.equity)}, worst drawdown ${worst.toFixed(1)} percent`}
      >
        <line
          x1={0}
          x2={width}
          y1={y(start)}
          y2={y(start)}
          className="stroke-line"
          strokeWidth={1}
          strokeDasharray="4 4"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={ddPath}
          fill="none"
          className="stroke-down/40"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={equityPath}
          fill="none"
          className={cn(last.equity >= start ? "stroke-up" : "stroke-down")}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="flex justify-between text-[10px] text-ink-4">
        <span>{first.at.slice(0, 10)}</span>
        <span>
          Dashed: starting {usd(start)} · red: drawdown (peak {worst.toFixed(1)}%)
        </span>
        <span>{last.at.slice(0, 10)}</span>
      </div>
    </div>
  );
}

function TradeRow({ trade }: { trade: LabTrade }) {
  return (
    <li className="border-b border-line/60 px-4 py-3 last:border-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-mono text-sm text-ink-2">{shortMint(trade.mint_address)}</span>
        <span className="flex items-center gap-3 text-sm">
          <Percent value={trade.return_pct} />
          <Money value={trade.net_pnl} signed />
          {trade.catastrophic ? (
            <span className="rounded-sm border border-down/40 bg-down/10 px-1.5 py-px text-[10px] uppercase text-down">
              Rug
            </span>
          ) : null}
          {trade.unsettled ? (
            <span className="rounded-sm border border-warn/40 bg-warn/10 px-1.5 py-px text-[10px] uppercase text-warn">
              Unsettled
            </span>
          ) : null}
        </span>
      </div>
      <p className="mt-0.5 text-[11px] text-ink-4">
        Opened {trade.opened_at.slice(0, 16).replace("T", " ")} · peak{" "}
        {multiple(trade.executable_peak_multiple)} executable
        {trade.observed_peak_multiple > trade.executable_peak_multiple
          ? ` (${multiple(trade.observed_peak_multiple)} printed)`
          : null}
      </p>
      <ol className="mt-1.5 space-y-0.5 text-xs">
        <li className="text-ink-3">
          <span className="inline-block w-20 font-mono">ENTRY</span>
          <Money value={trade.size_usd} /> at{" "}
          <span className="font-mono">{trade.entry_price}</span>
        </li>
        {trade.fills.map((fill, index) => (
          <li key={index} className="text-ink-2">
            <span className="inline-block w-20 font-mono">{multiple(fill.multiple)}</span>
            <span className="text-ink-3">{FILL_REASON_LABEL[fill.reason] ?? fill.reason}</span>{" "}
            <span className="font-mono">{fill.quantity_pct_of_initial.toFixed(0)}%</span> sold at{" "}
            <span className="font-mono">{fill.price_usd}</span> →{" "}
            <Money value={fill.net_proceeds} />
            <span className="text-ink-4">
              {" "}
              (cost {usd(fill.execution_cost)}
              {fill.rungs_covered.length > 1
                ? `, covered rungs ${fill.rungs_covered.map((r) => r + 1).join("+")}`
                : ""}
              )
            </span>
          </li>
        ))}
      </ol>
    </li>
  );
}

export function StrategyDetail({
  strategyId,
  mode,
  onClose,
}: {
  strategyId: string;
  mode: LabMode;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<TradeTab>("best");
  const { data, isPending, error, refetch } = useLabStrategyDetail(strategyId, mode);

  if (error) {
    return <ErrorState body="This strategy could not be loaded." onRetry={() => void refetch()} />;
  }
  if (isPending) return <Skeleton className="h-96 w-full" />;
  if (!data) return null;

  const trades =
    tab === "best"
      ? data.best_trades
      : tab === "worst"
        ? data.worst_trades
        : tab === "recent"
          ? data.recent_trades
          : undefined;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={onClose}
          className="text-sm text-ink-3 transition-colors hover:text-ink"
        >
          ← All strategies
        </button>
        <SimulatedBadge />
      </div>

      <Panel density="comfortable">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="flex items-baseline gap-2">
              <span className="font-mono text-xl font-semibold text-ink">{data.strategy_id}</span>
              <span className="text-md text-ink-2">{data.name}</span>
              {data.version ? (
                <span className="text-xs text-ink-3">v{data.version}</span>
              ) : null}
            </h2>
            {data.purpose ? (
              <p className="mt-1 max-w-3xl text-sm leading-relaxed text-ink-3">{data.purpose}</p>
            ) : null}
          </div>
          {data.row ? <FlagChips flags={data.row.flags} /> : null}
        </div>
      </Panel>

      {!data.has_results ? (
        <p className="px-4 py-8 text-center text-sm text-ink-3">
          No results have been recorded for this strategy yet.
        </p>
      ) : (
        <>
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <StatTile
              label="Simulated equity"
              value={usd(data.row?.final_equity)}
              tone={
                (data.row?.wallet_return_pct ?? 0) >= 0 ? "positive" : "negative"
              }
              hint={`from ${usd(data.row?.starting_capital)}`}
            />
            <StatTile
              label="Return"
              value={`${(data.row?.wallet_return_pct ?? 0) >= 0 ? "+" : ""}${(data.row?.wallet_return_pct ?? 0).toFixed(1)}%`}
              tone={(data.row?.wallet_return_pct ?? 0) >= 0 ? "positive" : "negative"}
            />
            <StatTile
              label="Trades"
              value={String(data.row?.n ?? 0)}
              hint={`${data.wallet?.closed_positions ?? 0} closed · ${data.wallet?.open_positions ?? 0} open`}
            />
            <StatTile
              label="Profit factor"
              value={data.row?.profit_factor === null ? "∞" : plain(data.row?.profit_factor)}
            />
            <StatTile
              label="Max drawdown"
              value={`${(data.row?.max_drawdown_pct ?? 0).toFixed(1)}%`}
              tone="negative"
            />
            <StatTile
              label="Mean P&L 95% CI"
              value={
                data.mean_pnl_ci95
                  ? `${usd(data.mean_pnl_ci95[0])} … ${usd(data.mean_pnl_ci95[1])}`
                  : "—"
              }
              hint="bootstrap, 2000 resamples"
            />
          </div>

          <Panel density="flush">
            <PanelHeader className="px-4 pt-4">
              <PanelTitle>Simulated equity and drawdown</PanelTitle>
            </PanelHeader>
            <EquityCurve
              points={data.equity_curve ?? []}
              start={data.row?.starting_capital ?? 1000}
            />
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel density="flush">
              <PanelHeader className="px-4 pt-4">
                <PanelTitle>Daily P&L</PanelTitle>
                <p className="mt-0.5 text-xs text-ink-3">Attributed to the day a position closed.</p>
              </PanelHeader>
              <ul className="px-4 pb-4 pt-2">
                {(data.daily_pnl ?? []).map((day) => (
                  <li
                    key={day.day}
                    className="flex items-center justify-between border-b border-line/50 py-1.5 text-sm last:border-0"
                  >
                    <span className="font-mono text-ink-3">{day.day}</span>
                    <span className="flex items-center gap-4">
                      <span className="text-xs text-ink-4">{day.trades} trades</span>
                      <Money value={day.pnl} signed />
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel density="flush">
              <PanelHeader className="px-4 pt-4">
                <PanelTitle>Trade distribution</PanelTitle>
              </PanelHeader>
              <ul className="px-4 pb-4 pt-2">
                {Object.entries(data.distribution ?? {}).map(([bucket, count]) => {
                  const total = Object.values(data.distribution ?? {}).reduce(
                    (a, b) => a + b,
                    0,
                  );
                  const share = total ? (count / total) * 100 : 0;
                  const negative = bucket.startsWith("loss");
                  return (
                    <li key={bucket} className="py-1 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-ink-3">{bucket.replaceAll("_", " ")}</span>
                        <span className="font-mono tabular-nums text-ink-2">{count}</span>
                      </div>
                      <div className="mt-0.5 h-1.5 w-full overflow-hidden rounded-full bg-raised">
                        <div
                          className={cn("h-full", negative ? "bg-down/60" : "bg-up/60")}
                          style={{ width: `${share}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Panel>
          </div>

          <Panel density="flush">
            <PanelHeader className="px-4 pt-4">
              <PanelTitle>Trade lifecycles</PanelTitle>
            </PanelHeader>
            <div className="px-4 py-3">
              <Tabs
                aria-label="Trade view"
                value={tab}
                onChange={setTab}
                items={[
                  { value: "best", label: "Best" },
                  { value: "worst", label: "Worst" },
                  { value: "recent", label: "Recent" },
                  { value: "blocked", label: "Blocked", count: data.blocked?.length },
                ]}
              />
            </div>
            {tab === "blocked" ? (
              <ul className="pb-2">
                {(data.blocked ?? []).map((entry, index) => (
                  <li
                    key={`${entry.mint_address}-${index}`}
                    className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line/60 px-4 py-2 text-sm last:border-0"
                  >
                    <span className="font-mono text-ink-2">{shortMint(entry.mint_address)}</span>
                    <span className="text-xs uppercase text-warn">
                      {entry.reason.replaceAll("_", " ")}
                    </span>
                    <span className="text-xs text-ink-4">
                      cash {usd(entry.cash_at_refusal)} · would have peaked{" "}
                      {multiple(entry.peak_multiple)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <ul>
                {(trades ?? []).map((trade, index) => (
                  <TradeRow key={`${trade.mint_address}-${index}`} trade={trade} />
                ))}
              </ul>
            )}
            <DatasetFooter dataset={data.dataset} />
          </Panel>
        </>
      )}
    </div>
  );
}

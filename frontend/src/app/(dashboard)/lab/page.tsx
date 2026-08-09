"use client";

import { useMemo, useState } from "react";

import { TokenIdentity } from "@/components/brand/token-identity";
import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useLab } from "@/hooks/use-paper";
import { hours, pct, sortLab, tone, usd, type LabSortKey } from "@/lib/paper";
import { cn } from "@/lib/utils";
import type { LabStrategy, SegmentRow, TradeCard } from "@/types/paper";

const COLUMNS: { key: LabSortKey; label: string }[] = [
  { key: "rank", label: "#" },
  { key: "net", label: "Net" },
  { key: "profit", label: "Profit factor" },
  { key: "drawdown", label: "Drawdown" },
  { key: "total", label: "Gross/marked" },
  { key: "win", label: "Win rate" },
  { key: "trades", label: "Closed" },
];

function Metric({
  label,
  value,
  signed,
}: {
  label: string;
  value: string | number | null | undefined;
  signed?: boolean;
}) {
  const text = typeof value === "string" && signed ? pct(value) : value;
  const flavour = typeof value === "string" && signed ? tone(value) : "neutral";
  return (
    <div className="rounded-card border border-line bg-surface/40 p-4">
      <p className="text-xs uppercase tracking-wide text-ink-faint">{label}</p>
      <p
        className={cn(
          "mt-2 text-2xl font-semibold tabular-nums text-ink",
          flavour === "positive" && "text-safe",
          flavour === "negative" && "text-danger",
        )}
      >
        {text ?? "—"}
      </p>
    </div>
  );
}

function SignedPct({ value }: { value: string | null }) {
  const flavour = tone(value);
  return (
    <span
      className={cn(
        "tabular-nums",
        flavour === "positive" && "text-safe",
        flavour === "negative" && "text-danger",
        flavour === "neutral" && "text-ink-dim",
      )}
    >
      {pct(value) ?? "—"}
    </span>
  );
}

function StrategyDetail({ strategy }: { strategy: LabStrategy }) {
  return (
    <Panel className="border-plasma/20">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Label>Selected rule</Label>
          <h2 className="mt-2 text-heading font-semibold text-ink">{strategy.name}</h2>
          <p className="mt-1 max-w-3xl text-sm text-ink-dim">{strategy.description}</p>
        </div>
        <div className="rounded-full border border-line px-3 py-1 text-xs text-ink-dim">
          Rank #{strategy.rank}
        </div>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Expectancy" value={usd(strategy.expectancy)} />
        <Metric label="Avg winner" value={usd(strategy.average_winner)} />
        <Metric label="Avg loser" value={usd(strategy.average_loser)} />
        <Metric label="Avg hold" value={hours(strategy.average_hold_hours)} />
        <Metric label="Capture" value={strategy.average_capture_pct} signed />
        <Metric label="Give-back" value={strategy.average_giveback_pct} signed />
        <Metric label="Slippage" value={usd(strategy.slippage_usd)} />
        <Metric label="Capital use" value={strategy.capital_utilization_pct} signed />
      </div>
      <dl className="mt-5 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {strategy.rules.map((rule) => (
          <div key={rule.label} className="flex items-baseline justify-between gap-4">
            <dt className="text-xs text-ink-faint">{rule.label}</dt>
            <dd className="text-right text-sm text-ink-dim">{rule.value}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function SegmentTable({ title, rows }: { title: string; rows: SegmentRow[] }) {
  return (
    <Panel density="compact">
      <h3 className="text-sm font-medium text-ink">{title}</h3>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <thead className="text-label uppercase tracking-wide text-ink-faint">
            <tr>
              <th className="py-2 text-left font-normal">Group</th>
              <th className="py-2 text-right font-normal">n</th>
              <th className="py-2 text-right font-normal">Net</th>
              <th className="py-2 text-right font-normal">Win</th>
              <th className="py-2 text-right font-normal">PF</th>
              <th className="py-2 text-right font-normal">Slip drag</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-t border-line/60">
                <td className="py-2 text-ink">{row.name}</td>
                <td className="py-2 text-right tabular-nums text-ink-dim">{row.n}</td>
                <td className="py-2 text-right"><SignedPct value={row.net_return_pct} /></td>
                <td className="py-2 text-right"><SignedPct value={row.win_rate_pct} /></td>
                <td className="py-2 text-right tabular-nums text-ink-dim">{row.profit_factor ?? "—"}</td>
                <td className="py-2 text-right"><SignedPct value={row.slippage_drag_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function TradeList({ title, items }: { title: string; items: TradeCard[] }) {
  return (
    <Panel density="compact">
      <h3 className="text-sm font-medium text-ink">{title}</h3>
      <div className="mt-3 flex flex-col divide-y divide-line/60">
        {items.map((item) => (
          <div key={item.mint_address} className="grid gap-2 py-3 sm:grid-cols-5">
            <div className="sm:col-span-2">
              <TokenIdentity
                mint={item.mint_address}
                symbol={item.symbol}
                imageUrl={item.image_url}
                size="xs"
              />
            </div>
            <SignedPct value={item.net_return_pct} />
            <span className="text-sm text-ink-dim">{usd(item.entry_liquidity_usd) ?? "No liquidity"}</span>
            <span className="text-sm text-ink-dim">{item.category ?? "Unknown"}</span>
          </div>
        ))}
        {items.length === 0 ? <p className="py-4 text-sm text-ink-faint">No trades in this slice.</p> : null}
      </div>
    </Panel>
  );
}

export default function StrategyLabPage() {
  const lab = useLab();
  const [sort, setSort] = useState<LabSortKey>("rank");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const rows = useMemo(
    () => sortLab(lab.data?.strategies ?? [], sort),
    [lab.data?.strategies, sort],
  );
  const selected = rows.find((row) => row.id === selectedId) ?? rows[0];

  if (lab.isError) {
    return (
      <ErrorState
        body="The Strategy Lab could not load. The paper history is intact; this page is a read-only replay."
        onRetry={() => void lab.refetch()}
      />
    );
  }

  if (lab.isPending || !lab.data) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-28 rounded-card" />
        <Skeleton className="h-80 rounded-card" />
      </div>
    );
  }

  const integrity = lab.data.data_integrity;
  const production = lab.data.production_summary;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 pb-16">
      <header>
        <Label>Strategy Lab V2</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">
          Evidence from Generation 2 paper trades
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-dim">
          {lab.data.methodology}
        </p>
      </header>

      <Panel className="border-plasma/20 bg-plasma/[0.03]">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <Label>Final research decision</Label>
            <h2 className="mt-2 text-heading font-semibold text-ink">
              {lab.data.final_decision_code}. {lab.data.final_decision}
            </h2>
          </div>
          <p className="max-w-xl text-sm leading-relaxed text-ink-dim">
            {integrity.verdict} Gen 1 remains archived/historical and is excluded from optimisation.
          </p>
        </div>
      </Panel>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Metric label="Gen 2 positions" value={integrity.positions} />
        <Metric label="Closed" value={integrity.closed_positions} />
        <Metric label="Audited closed" value={integrity.audited_closed_positions} />
        <Metric label="Manual overrides" value={integrity.manual_overrides} />
        <Metric label="Archived Gen 1" value={integrity.archived_generation_positions} />
      </section>
      <section className="grid gap-3 sm:grid-cols-3">
        <Metric label="Legacy execution rows" value={integrity.legacy_execution_model_rows} />
        <Metric label="Jupiter execution rows" value={integrity.jupiter_execution_model_rows} />
        <Metric label="Unknown execution rows" value={integrity.unknown_execution_model_rows} />
      </section>

      <Panel>
        <Label>Execution model performance</Label>
        <p className="mt-2 text-sm text-ink-dim">
          Closed audit rows are grouped by the execution model that produced their stored net result.
          Historical legacy rows and future Jupiter rows are not blended.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-ink-faint">
              <tr>
                <th className="py-2">Model</th>
                <th className="py-2 text-right">Trades</th>
                <th className="py-2 text-right">Gross P/L</th>
                <th className="py-2 text-right">Net P/L</th>
                <th className="py-2 text-right">Win rate</th>
                <th className="py-2 text-right">Profit factor</th>
                <th className="py-2 text-right">Fees</th>
                <th className="py-2 text-right">Slippage / drag</th>
              </tr>
            </thead>
            <tbody>
              {lab.data.execution_models.map((row) => (
                <tr key={row.model_version} className="border-t border-line/70">
                  <td className="py-3 font-medium text-ink">{row.label}</td>
                  <td className="py-3 text-right tabular-nums text-ink-dim">{row.trades}</td>
                  <td className="py-3 text-right tabular-nums text-ink-dim">{usd(row.gross_return_usd)}</td>
                  <td className="py-3 text-right tabular-nums"><span className={tone(row.net_return_usd) === "positive" ? "text-safe" : tone(row.net_return_usd) === "negative" ? "text-danger" : "text-ink-dim"}>{usd(row.net_return_usd)}</span></td>
                  <td className="py-3 text-right"><SignedPct value={row.win_rate_pct} /></td>
                  <td className="py-3 text-right tabular-nums text-ink-dim">{row.profit_factor ?? "—"}</td>
                  <td className="py-3 text-right tabular-nums text-ink-dim">{usd(row.fees_usd)}</td>
                  <td className="py-3 text-right tabular-nums text-ink-dim">{usd(row.slippage_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <section>
        <Label>Current Production Strategy</Label>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Net return" value={production.net_return_pct} signed />
          <Metric label="Gross/marked" value={production.total_return_pct} signed />
          <Metric label="Profit factor" value={production.profit_factor} />
          <Metric label="Win rate" value={production.win_rate_pct} signed />
          <Metric label="Expectancy" value={usd(production.expectancy)} />
          <Metric label="Drawdown" value={production.max_drawdown_pct} signed />
          <Metric label="Avg winner" value={usd(production.average_winner)} />
          <Metric label="Avg loser" value={usd(production.average_loser)} />
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-heading font-medium text-ink">Strategy Leaderboard</h2>
        <div className="overflow-x-auto rounded-card border border-line">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-line text-label uppercase tracking-wide text-ink-faint">
                <th className="px-3 py-2 text-left font-normal">Strategy</th>
                {COLUMNS.filter((column) => column.key !== "rank").map((column) => (
                  <th key={column.key} className="px-3 py-2 text-right font-normal">
                    <button
                      type="button"
                      onClick={() => setSort(column.key)}
                      className={cn("hover:text-ink", sort === column.key && "text-plasma")}
                    >
                      {column.label}
                    </button>
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-normal">vs V1</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => setSelectedId(row.id)}
                  className={cn(
                    "cursor-pointer border-b border-line/60 transition-colors hover:bg-surface/60",
                    row.id === selected?.id && "bg-plasma/[0.05]",
                  )}
                >
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-xs tabular-nums text-ink-faint">#{row.rank}</span>
                      <span className="font-medium text-ink">{row.name}</span>
                      {row.is_baseline ? (
                        <span className="rounded-full border border-plasma/30 px-2 py-0.5 text-[10px] uppercase text-plasma">
                          V1
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-right"><SignedPct value={row.net_return_pct} /></td>
                  <td className="px-3 py-3 text-right tabular-nums text-ink-dim">{row.profit_factor ?? "—"}</td>
                  <td className="px-3 py-3 text-right"><SignedPct value={row.max_drawdown_pct} /></td>
                  <td className="px-3 py-3 text-right"><SignedPct value={row.total_return_pct} /></td>
                  <td className="px-3 py-3 text-right"><SignedPct value={row.win_rate_pct} /></td>
                  <td className="px-3 py-3 text-right tabular-nums text-ink-dim">{row.closed_count}</td>
                  <td className="px-3 py-3 text-right"><SignedPct value={row.baseline_difference_pct} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected ? <StrategyDetail strategy={selected} /> : null}

      <section className="grid gap-3 lg:grid-cols-2">
        {lab.data.findings.map((finding) => (
          <Panel key={finding.headline} density="compact">
            <h3 className="text-sm font-medium text-ink">{finding.headline}</h3>
            <p className="mt-2 text-xs leading-relaxed text-ink-dim">{finding.detail}</p>
          </Panel>
        ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <SegmentTable title="Entry market cap" rows={lab.data.pattern_analysis.entry_market_cap} />
        <SegmentTable title="Liquidity" rows={lab.data.pattern_analysis.liquidity} />
        <SegmentTable title="Radar score" rows={lab.data.pattern_analysis.radar_score} />
        <SegmentTable title="Age at entry" rows={lab.data.pattern_analysis.age} />
        <SegmentTable title="Holding time" rows={lab.data.pattern_analysis.holding_time} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <TradeList title="Largest winners" items={lab.data.largest_winners} />
        <TradeList title="Largest losers" items={lab.data.largest_losers} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <Label>Suggested improvements</Label>
          <div className="mt-3 flex flex-col gap-3">
            {lab.data.suggestions.map((item) => (
              <div key={item.title} className="rounded-card border border-line p-3">
                <p className="font-medium text-ink">{item.title}</p>
                <p className="mt-1 text-xs text-ink-faint">
                  Confidence: {item.confidence} · n={item.sample_size}
                </p>
                <p className="mt-2 text-sm text-ink-dim">{item.expected_improvement}</p>
                <p className="mt-1 text-xs text-ink-faint">{item.trade_offs}</p>
              </div>
            ))}
          </div>
        </Panel>
        <Panel>
          <Label>Rejected ideas</Label>
          <div className="mt-3 flex flex-col gap-2">
            {lab.data.rejected_ideas.slice(0, 8).map((item) => (
              <div key={item.strategy_id} className="rounded-card border border-line p-3">
                <p className="font-medium text-ink">{item.strategy_id}</p>
                <p className="mt-1 text-xs text-ink-dim">{item.reason}</p>
              </div>
            ))}
          </div>
        </Panel>
      </section>

      <Panel density="compact">
        <p className="text-xs leading-relaxed text-ink-dim">{lab.data.cost_disclosure}</p>
      </Panel>
    </div>
  );
}

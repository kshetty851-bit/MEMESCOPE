"use client";

import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";

import { DrawdownChart, EquityChart, MonthlyBars } from "./charts";
import { CodedList, Section } from "./generic";
import { count, pct, utcDate } from "./format";
import { MetricTiles, TradeLog } from "./metrics";
import { RobustnessSections } from "./robustness";
import { RunStatus } from "./run-status";
import { TargetPanel } from "./targets";
import { tradesCsvUrl } from "./urls";
import type { BacktestResult, Coded, RunDetail } from "./types";

export function DataLine({ data }: { data: BacktestResult["data"] }) {
  return (
    <Panel density="compact" data-testid="data-line">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-3">
        <span>
          <span className="text-ink-2">{data.symbol}</span> · {data.timeframe}
        </span>
        <span>
          {utcDate(data.start)} to {utcDate(data.end)}
        </span>
        <span>{count(data.bars)} bars</span>
        <span>Sources: {data.sources.join(", ") || "—"}</span>
        <span className="inline-flex items-center gap-1.5">
          Data grade{" "}
          <Badge tone={data.quality_grade <= "B" ? "safe" : "warn"}>
            {data.quality_grade}
          </Badge>
        </span>
        <span>Coverage {pct(data.coverage_pct)}</span>
        <span>
          Lower-timeframe data: {data.lower_tf_available ? "available" : "not available"}
        </span>
        <span>Higher timeframe: {data.htf_derived}</span>
      </div>
    </Panel>
  );
}

/** A backtest result: tiles, curves, targets, every trade, and what was assumed. */
export function BacktestView({
  detail,
  priceDecimals = 5,
  disclaimer,
}: {
  detail: RunDetail;
  priceDecimals?: number;
  disclaimer?: Coded | null;
}) {
  const { run, result } = detail;
  if (!result || result.type !== "backtest") {
    return <RunStatus run={run} />;
  }
  const skipped = result.skipped_text ?? [];

  return (
    <div className="flex flex-col gap-4" data-testid="backtest-view">
      <DataLine data={result.data} />
      <MetricTiles metrics={result.metrics} />

      <Section title="Equity curve" testId="equity-section">
        <EquityChart
          points={result.equity_curve}
          startingBalance={result.metrics.starting_balance}
        />
      </Section>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Drawdown">
          <DrawdownChart
            points={result.drawdown}
            maxDrawdownPct={result.metrics.max_drawdown_pct}
          />
        </Section>
        <Section title="Monthly returns">
          <MonthlyBars months={result.months} />
        </Section>
      </div>

      <TargetPanel
        title="Monthly target analysis"
        report={result.targets}
        disclaimer={disclaimer}
      />

      <Section
        title="Trade log"
        hint="Every trade the run took, losers included."
        testId="trades-section"
      >
        <div className="mb-3">
          <a
            href={tradesCsvUrl(run.id)}
            download
            data-testid="export-trades"
            className="inline-flex h-8 items-center rounded-sm border border-line px-3 text-xs text-ink hover:border-line-strong hover:bg-raised/80"
          >
            Export trades CSV
          </a>
        </div>
        <TradeLog trades={result.trades} priceDecimals={priceDecimals} />
      </Section>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section
          title="Skipped signals"
          hint="Signals the strategy produced that were not traded."
          testId="skipped"
        >
          {skipped.length === 0 ? (
            <p className="text-sm text-ink-3">No signal was skipped.</p>
          ) : (
            <ul className="flex flex-col gap-1.5 text-sm text-ink-2">
              {skipped.map((s) => (
                <li key={s.code} className="flex gap-2">
                  <span data-numeric className="min-w-8 text-right text-ink">
                    {s.count}
                  </span>
                  <span>{s.text}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Assumptions" hint="Disclosed with every run." testId="assumptions">
          <CodedList items={result.assumptions} empty="No assumptions were recorded." />
        </Section>
      </div>

      <RobustnessSections
        baseline={result.baseline}
        monteCarlo={result.monte_carlo}
        bootstrap={result.bootstrap}
      />
    </div>
  );
}

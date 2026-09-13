"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import { useForexLabData, useForexLabLatest } from "./hooks";
import type { ConfigResult, DataHealth, GateSpec, LatestRun, SweepResult } from "./types";

/**
 * FOREX LAB — BACKTEST ONLY.
 *
 * Does a hedged grid on EUR/USD make money on a $1,000 wallet at 10x leverage
 * over 2020–2026?
 *
 * This page REPORTS a replay. There is no wallet behind it, live or paper, and
 * nothing here has ever placed an order. It applies no rule of its own — a
 * threshold written here would be a second, unpublished gate competing with
 * the one the sweep was judged against, and the two would disagree the first
 * time either moved.
 *
 * Three things are given the same prominence as the headline result, because a
 * reader who misses any of them will misread everything else:
 *
 *  - the COVERAGE banner, because a sweep over a half-loaded window cannot
 *    satisfy a gate that asks for six years and must not look as though it did;
 *  - the BLOWN column, because a profit factor computed over an account that
 *    passed through zero is arithmetic about a thing that stopped existing;
 *  - the BEST MONTH share, because a result that is one good month and a slow
 *    bleed is not a strategy.
 */

function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

function usd(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function pct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function day(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "—";
}

/** The headline. Deliberately unmissable and deliberately plain-spoken. */
function Verdict({ run }: { run: LatestRun }) {
  const passed = run.gate_passed === true;
  const result = run.result;
  return (
    <Panel>
      <div className="flex flex-col gap-3 p-6">
        <span className="text-xs uppercase tracking-widest text-ink-dim">
          Acceptance gate — stated before the sweep ran, never adjusted
        </span>
        <span className={`text-2xl font-bold ${passed ? "text-up" : "text-danger"}`}>
          {passed ? "PASS — GATE CLEARED" : "FAIL — GATE NOT CLEARED"}
        </span>
        <p className="max-w-3xl text-sm text-ink-dim">
          Best configuration by profit factor is{" "}
          <strong className="text-ink">{run.best_config}</strong>. A hedged grid
          holds a long and a short at every level and never nets them; there is no
          per-order stop loss, only the margin cap and the re-centre.
        </p>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-dim">
          <span>{run.symbol}</span>
          <span>{(run.candles ?? 0).toLocaleString()} one-minute candles</span>
          <span>
            {day(run.first_minute)} → {day(run.last_minute)}
          </span>
          {result ? <span>{result.results.length} configurations</span> : null}
          {run.git_sha ? <span>git {run.git_sha.slice(0, 7)}</span> : null}
        </div>
      </div>
    </Panel>
  );
}

/**
 * The window the brief asked for, against the window actually replayed.
 *
 * A sweep over eighteen months rendered under a 2020–2026 heading is a page
 * that lies, and "positive in 4 of 6 years" cannot be satisfied by a window
 * that does not contain six years.
 */
function CoverageBanner({ run }: { run: LatestRun }) {
  const want = run.gate;
  const first = run.first_minute?.slice(0, 10);
  const last = run.last_minute?.slice(0, 10);
  const windowStart = run.window?.start ?? "2020-01-01";
  const windowEnd = run.window?.end ?? "2026-06-30";
  if (!first || !last) return null;
  const short = first > windowStart || last < windowEnd;
  if (!short) return null;
  return (
    <Panel>
      <div className="flex flex-col gap-2 border-l-2 border-warn p-4">
        <span className="text-sm font-semibold text-warn">Partial coverage</span>
        <p className="max-w-3xl text-sm text-ink-dim">
          The window is{" "}
          <strong className="text-ink">
            {windowStart} → {windowEnd}
          </strong>
          ; this replay covers{" "}
          <strong className="text-ink">
            {first} → {last}
          </strong>
          . Every number below is about the window that was loaded. The gate asks
          for a positive result in {want.years_positive_min} of{" "}
          {want.years_positive_of} full years including {want.must_include_year},
          and a window that does not contain those years cannot satisfy it.
        </p>
      </div>
    </Panel>
  );
}

const GATE_LABELS: Record<string, string> = {
  "pf>=1.3": "Profit factor ≥ 1.3",
  "positive in >=4 of 6 years": "Positive in ≥ 4 of 6 full years",
  "2022 positive": "2022 positive",
  "max DD < 25%": "Max drawdown < 25%",
  "no month > 30% of profit": "No single month > 30% of total profit",
};

function GateTable({ result, spec }: { result: SweepResult; spec: GateSpec }) {
  const checks = Object.entries(result.gate?.checks ?? {});
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Acceptance gate</PanelTitle>
      </PanelHeader>
      <div className="divide-y divide-line">
        {checks.map(([condition, ok]) => (
          <div
            key={condition}
            className="flex items-start justify-between gap-4 px-4 py-3"
          >
            <span className="text-sm text-ink">
              {GATE_LABELS[condition] ?? condition}
            </span>
            <span
              className={`shrink-0 rounded px-2 py-0.5 text-xs font-semibold ${
                ok ? "bg-up/15 text-up" : "bg-danger/15 text-danger"
              }`}
            >
              {ok ? "PASS" : "FAIL"}
            </span>
          </div>
        ))}
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
        All five must hold. The denominator is the {spec.full_years.length} full
        years {spec.full_years[0]}–{spec.full_years[spec.full_years.length - 1]};{" "}
        {spec.partial_year} is January to June and is counted in nothing.
      </p>
    </Panel>
  );
}

function SweepTable({ results, spec }: { results: ConfigResult[]; spec: GateSpec }) {
  const ranked = [...results].sort(
    (a, b) => (b.profit_factor ?? -1) - (a.profit_factor ?? -1),
  );
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Every configuration</PanelTitle>
      </PanelHeader>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[52rem] text-sm">
          <thead className="text-xs uppercase tracking-wide text-ink-dim">
            <tr className="border-b border-line">
              <th className="px-3 py-2 text-left font-medium">Config</th>
              <th className="px-3 py-2 text-right font-medium">PF</th>
              <th className="px-3 py-2 text-right font-medium">Return</th>
              <th className="px-3 py-2 text-right font-medium">Max DD</th>
              <th className="px-3 py-2 text-right font-medium">Low water</th>
              <th className="px-3 py-2 text-right font-medium">Trades</th>
              <th className="px-3 py-2 text-right font-medium">Re-centres</th>
              <th className="px-3 py-2 text-right font-medium">Stop-outs</th>
              <th className="px-3 py-2 text-right font-medium">Rejected</th>
              <th className="px-3 py-2 text-right font-medium">Years +</th>
              <th className="px-3 py-2 text-right font-medium">Best month</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {ranked.map((r) => (
              <tr key={r.config.name} className={r.blown ? "bg-danger/5" : undefined}>
                <td className="px-3 py-2 font-mono text-xs text-ink">
                  {r.config.name}
                  {r.blown ? (
                    <span className="ml-2 rounded bg-danger/15 px-1.5 py-0.5 text-[10px] font-semibold text-danger">
                      BLOWN
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {fmt(r.profit_factor, 3)}
                </td>
                <td
                  className={`px-3 py-2 text-right tabular-nums ${
                    r.total_return_pct >= 0 ? "text-up" : "text-danger"
                  }`}
                >
                  {fmt(r.total_return_pct)}%
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {fmt(r.max_drawdown_pct)}%
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                  {usd(r.min_equity)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                  {r.trades.toLocaleString()}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                  {r.recenters.toLocaleString()}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                  {r.stopouts.toLocaleString()}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                  {r.rejected_fills.toLocaleString()}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                  {r.years_positive} / {spec.years_positive_of}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                  {pct(r.best_month_share)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
        <strong>Low water</strong> is the lowest equity the account ever showed,
        measured at the worse extreme of every candle rather than at a daily
        close. A row marked <strong className="text-danger">BLOWN</strong> passed
        through zero, and its profit factor and return are arithmetic about an
        account that had stopped existing. <strong>Best month</strong> is the most
        profitable month as a share of the run&rsquo;s total profit, so it exceeds
        100% whenever the other months lost money between them.
      </p>
    </Panel>
  );
}

function PerYear({ results, spec }: { results: ConfigResult[]; spec: GateSpec }) {
  const years = Array.from(
    new Set(results.flatMap((r) => Object.keys(r.per_year))),
  ).sort();
  const ranked = [...results].sort(
    (a, b) => (b.profit_factor ?? -1) - (a.profit_factor ?? -1),
  );
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Profit and loss by year, on a $1,000 wallet</PanelTitle>
      </PanelHeader>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead className="text-xs uppercase tracking-wide text-ink-dim">
            <tr className="border-b border-line">
              <th className="px-3 py-2 text-left font-medium">Config</th>
              {years.map((y) => (
                <th key={y} className="px-3 py-2 text-right font-medium">
                  {y}
                  {Number(y) === spec.partial_year ? (
                    <span className="ml-1 text-[10px] text-ink-dim">½</span>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {ranked.map((r) => (
              <tr key={r.config.name}>
                <td className="px-3 py-2 font-mono text-xs text-ink">
                  {r.config.name}
                </td>
                {years.map((y) => {
                  const v = r.per_year[y] ?? 0;
                  return (
                    <td
                      key={y}
                      className={`px-3 py-2 text-right tabular-nums ${
                        v > 0 ? "text-up" : v < 0 ? "text-danger" : "text-ink-dim"
                      }`}
                    >
                      {v >= 0 ? "+" : ""}
                      {v.toFixed(0)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
        {spec.partial_year} is January to June — half a year, marked ½, and
        counted in nothing.
      </p>
    </Panel>
  );
}

function Costs({ best }: { best: ConfigResult }) {
  const rows: [string, string, string?][] = [
    ["Banked by take-profits", usd(best.tp_pnl)],
    ["Realised on re-centres", usd(best.recenter_loss)],
    ["Realised on stop-outs", usd(best.stopout_loss)],
    ["Swap", usd(best.swap_paid)],
    [
      "Spread and slippage",
      usd(-best.spread_paid),
      "already inside the lines above — every fill price is the price after the spread",
    ],
  ];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Cost breakdown — {best.config.name}</PanelTitle>
      </PanelHeader>
      <div className="divide-y divide-line">
        {rows.map(([label, value, note]) => (
          <div key={label} className="flex items-start justify-between gap-4 px-4 py-3">
            <div className="flex flex-col">
              <span className="text-sm text-ink">{label}</span>
              {note ? <span className="text-xs text-ink-dim">{note}</span> : null}
            </div>
            <span className="shrink-0 tabular-nums text-sm text-ink">{value}</span>
          </div>
        ))}
        <div className="flex items-center justify-between gap-4 px-4 py-3">
          <span className="text-sm font-semibold text-ink">Final equity</span>
          <span
            className={`tabular-nums text-sm font-semibold ${
              best.final_equity >= best.start_equity ? "text-up" : "text-danger"
            }`}
          >
            {usd(best.final_equity)}
          </span>
        </div>
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
        {best.fills.toLocaleString()} fills, {best.trades.toLocaleString()} closed
        positions, {best.rejected_fills.toLocaleString()} fills rejected by the 90%
        margin cap, {best.recenters.toLocaleString()} re-centres,{" "}
        {best.stopouts.toLocaleString()} stop-outs.
      </p>
    </Panel>
  );
}

function Baselines({ result }: { result: SweepResult }) {
  const hedged = [...result.results]
    .filter((r) => r.config.stop_multiplier > 0)
    .sort((a, b) => (b.profit_factor ?? -1) - (a.profit_factor ?? -1))[0];
  const neutral = [...result.results]
    .filter((r) => r.config.stop_multiplier === 0)
    .sort((a, b) => (b.profit_factor ?? -1) - (a.profit_factor ?? -1))[0];
  const bh = result.buy_and_hold;
  const beat = (a?: ConfigResult, b?: number) =>
    a && b !== undefined ? (a.final_equity > b ? "beat" : "did not beat") : "—";
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Against the baselines</PanelTitle>
      </PanelHeader>
      <div className="divide-y divide-line">
        {[
          ["Best hedged grid", hedged?.config.name, hedged?.final_equity, hedged?.total_return_pct],
          ["Best neutral grid (no stop orders)", neutral?.config.name, neutral?.final_equity, neutral?.total_return_pct],
          ["Buy and hold, 1 micro lot", bh?.name, bh?.final_equity, bh?.total_return_pct],
        ].map(([label, name, equity, ret]) => (
          <div key={String(label)} className="flex items-center justify-between gap-4 px-4 py-3">
            <div className="flex flex-col">
              <span className="text-sm text-ink">{String(label)}</span>
              {name ? (
                <span className="font-mono text-xs text-ink-dim">{String(name)}</span>
              ) : null}
            </div>
            <div className="flex shrink-0 gap-6 tabular-nums text-sm">
              <span className="text-ink">{usd(equity as number)}</span>
              <span
                className={
                  (ret as number) >= 0 ? "text-up" : "text-danger"
                }
              >
                {fmt(ret as number)}%
              </span>
            </div>
          </div>
        ))}
      </div>
      <p className="border-t border-line px-4 py-3 text-sm text-ink-dim">
        The hedged grid <strong className="text-ink">{beat(hedged, neutral?.final_equity)}</strong>{" "}
        the neutral-grid baseline and{" "}
        <strong className="text-ink">{beat(hedged, bh?.final_equity)}</strong>{" "}
        buy-and-hold.
      </p>
    </Panel>
  );
}

function Caveats() {
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>What this is not</PanelTitle>
      </PanelHeader>
      <div className="flex flex-col gap-3 p-4 text-sm text-ink-dim">
        <p>
          <strong className="text-ink">Nothing here has traded.</strong> There is
          no wallet behind this lab, live or paper. Every figure is a replay over
          stored Dukascopy candles, and fill assumptions that hold in a replay —
          that a limit at a level always fills when price touches it, that the
          margin cap is the only thing a broker ever refuses — are assumptions,
          not observations.
        </p>
        <p>
          <strong className="text-ink">
            The gap model does not charge the worst of a weekend.
          </strong>{" "}
          An order the market gapped over fills at its own level, so a stop
          crossed by a 40-pip Sunday gap is flattered by exactly the amount a
          limit crossed by the same gap is penalised. The grid holds equal numbers
          of both, so the errors cancel in aggregate — but a grid is short
          volatility across a weekend, and this is the one cost it is not made to
          pay in full.
        </p>
        <p>
          <strong className="text-ink">
            Six and a half years of one pair is one sample of one regime.
          </strong>{" "}
          A grid&rsquo;s headline number is famously a function of the window it
          ran over. The gate was written down before the sweep ran and has not
          been adjusted since, which is the only thing separating this from a
          search for a flattering window.
        </p>
      </div>
    </Panel>
  );
}

function DataPanel({ data }: { data: DataHealth }) {
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Data</PanelTitle>
      </PanelHeader>
      <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
        <div className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-ink-dim">Candles</span>
          <span className="text-lg font-semibold tabular-nums text-ink">
            {data.candles.toLocaleString()}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-ink-dim">From</span>
          <span className="text-lg font-semibold tabular-nums text-ink">
            {day(data.first_minute)}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-ink-dim">To</span>
          <span className="text-lg font-semibold tabular-nums text-ink">
            {day(data.last_minute)}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-ink-dim">Target</span>
          <span className="text-lg font-semibold tabular-nums text-ink-dim">
            {data.window.start.slice(0, 4)}–{data.window.end.slice(0, 4)}
          </span>
        </div>
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
        One-minute bid/ask candles aggregated here from Dukascopy tick files. The
        aggregation is checked against Dukascopy&rsquo;s own published candles on
        days sampled at random from what is loaded.
      </p>
    </Panel>
  );
}

export function ForexLabPage() {
  const latest = useForexLabLatest();
  const data = useForexLabData();

  if (latest.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (latest.isError || !latest.data) {
    return (
      <ErrorState
        body="Could not load the Forex Lab."
        onRetry={() => void latest.refetch()}
      />
    );
  }

  const run = latest.data;

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-ink">Forex Lab</h1>
        <p className="text-sm text-ink-dim">
          A hedged grid on EUR/USD, replayed over one-minute Dukascopy candles.
          $1,000 paper wallet at 10x leverage, 1 micro lot an order, 0.8-pip
          spread, 0.2-pip slippage on stop fills, swap at every 17:00 New York
          rollover. Backtest only — no live trading, no paper feed, no wallet.
        </p>
      </header>

      {data.data ? <DataPanel data={data.data} /> : null}

      {!run.has_run || !run.result ? (
        <EmptyState
          title="No sweep published yet"
          body={
            "The backtest is run by an operator command, not by loading this page. " +
            "Run the sweep, then publish it, and the result appears here. Until " +
            "then this lab has not run — which is a different fact from having " +
            "run and found nothing."
          }
        />
      ) : (
        <>
          <Verdict run={run} />
          <CoverageBanner run={run} />
          <GateTable result={run.result} spec={run.gate} />
          <SweepTable results={run.result.results} spec={run.gate} />
          <PerYear results={run.result.results} spec={run.gate} />
          {(() => {
            const best = run.result.results.find(
              (r) => r.config.name === run.best_config,
            );
            return best ? <Costs best={best} /> : null;
          })()}
          <Baselines result={run.result} />
        </>
      )}

      <Caveats />
    </div>
  );
}

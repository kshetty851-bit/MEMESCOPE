"use client";

import { useMemo, useState } from "react";

import { BarChart, ChartFrame, LineChart, bucket } from "@/components/paper/lab-charts";
import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useLab, useLabTokens } from "@/hooks/use-paper";
import { EXIT_ORDER, hours, pct, sortLab, tone, type LabSortKey } from "@/lib/paper";
import { cn } from "@/lib/utils";
import type { LabStrategy } from "@/types/paper";

/**
 * THE STRATEGY LAB
 *
 * Every published exit rule replayed over the same detections and the same
 * stored prices. Only the exit logic differs, so a difference in the table is a
 * difference in the rule and nothing else.
 *
 * **Equal Weight v1 is frozen and is never tuned in response to this page.**
 * It is the permanent benchmark; moving it would restate every comparison ever
 * drawn against it. If it loses, the page says so at the same size as it would
 * have said it won — that is the entire reason to build a lab rather than a
 * leaderboard.
 *
 * Two figures are shown side by side everywhere: the **marked** return, which
 * includes open positions at their latest price, and the **realised** return,
 * which counts only closed trades. Win rate, profit factor and drawdown are
 * closed-only, so a rule whose headline comes from open marks would otherwise
 * read as though it had earned it.
 */

const COLUMNS: { key: LabSortKey; label: string; hint?: string }[] = [
  { key: "rank", label: "#" },
  { key: "total", label: "Marked", hint: "Includes open positions at the latest price" },
  { key: "realised", label: "Realised", hint: "Closed trades only" },
  {
    key: "net",
    label: "Net of costs",
    hint: "After the venue's fee and the order's price impact",
  },
  { key: "win", label: "Win rate" },
  { key: "drawdown", label: "Drawdown", hint: "Realised curve; smaller is better" },
  { key: "profit", label: "Profit factor" },
  { key: "trades", label: "Trades" },
];

function Value({
  value,
  signed,
  className,
}: {
  value: string | null;
  signed?: boolean;
  className?: string;
}) {
  const rendered = signed ? pct(value) : value;
  const flavour = signed ? tone(value) : "neutral";
  return (
    <span
      className={cn(
        "tabular-nums",
        rendered === null && "text-ink-faint",
        flavour === "positive" && "text-safe",
        flavour === "negative" && "text-danger",
        flavour === "neutral" && rendered !== null && "text-ink-dim",
        className,
      )}
    >
      {rendered ?? "—"}
    </span>
  );
}

export default function StrategyLabPage() {
  const lab = useLab();
  const tokens = useLabTokens();
  const [sort, setSort] = useState<LabSortKey>("rank");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const rows = useMemo(
    () => sortLab(lab.data?.strategies ?? [], sort),
    [lab.data, sort],
  );
  const selected: LabStrategy | undefined =
    rows.find((row) => row.id === selectedId) ?? rows[0];

  if (lab.isError) {
    return (
      <ErrorState
        body="The Strategy Lab is not responding. Nothing here is stored — it is replayed on request, so this is a read failure and the history is intact."
        onRetry={() => void lab.refetch()}
      />
    );
  }

  if (lab.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 rounded-card" />
        <Skeleton className="h-64 rounded-card" />
      </div>
    );
  }

  const { strategies, findings, unavailable, methodology, baseline_id } = lab.data;
  const baseline = strategies.find((item) => item.is_baseline);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 pb-16">
      <header>
        <Label>Strategy lab</Label>
        <h1 className="mt-2 text-title font-semibold text-ink">
          Every published rule, over the same history
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-ink-dim">
          {lab.data.detections} detections replayed over{" "}
          {lab.data.observed_days ?? "—"} days
          {lab.data.unpriced_detections > 0
            ? `, ${lab.data.unpriced_detections} never priced and so never entered`
            : ""}
          . Same entries, same prices; only the exit rule changes.
        </p>
      </header>

      {/* The two distinctions that have to stay visible: what a lab return
          is not, and what the net figures do and do not charge. */}
      <Panel density="compact" className="border-line/60">
        <p className="text-xs leading-relaxed text-ink-dim">{methodology}</p>
        <p className="mt-3 text-xs leading-relaxed text-ink-dim">
          {lab.data.cost_disclosure}
        </p>
        <dl className="mt-3 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
          {lab.data.cost_rules.map((rule) => (
            <div key={rule.label} className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-ink-faint">{rule.label}</dt>
              <dd className="text-right text-xs text-ink-dim">{rule.value}</dd>
            </div>
          ))}
        </dl>
      </Panel>

      {/* The comparison this page invites, and the reason it does not hold.
          Raised by a reader who put the benchmark row next to the wallet's ROI
          and found two different numbers — which the old copy encouraged by
          calling this row "the live wallet's rule". */}
      {lab.data.entry_divergence.positions > 0 ? (
        <Panel density="compact" className="border-warn/20 bg-warn/[0.03]">
          <Label>Not the same number as the paper wallet</Label>
          <p className="mt-2 max-w-3xl whitespace-pre-line text-xs leading-relaxed text-ink-dim">
            {lab.data.entry_divergence.explanation}
          </p>
          <dl className="mt-3 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-ink-faint">Positions compared</dt>
              <dd className="text-xs tabular-nums text-ink-dim">
                {lab.data.entry_divergence.positions}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-ink-faint">Wallet paid more</dt>
              <dd className="text-xs tabular-nums text-ink-dim">
                {lab.data.entry_divergence.wallet_paid_more} of{" "}
                {lab.data.entry_divergence.positions}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-ink-faint">Median entry ratio</dt>
              <dd className="text-xs tabular-nums text-ink-dim">
                {lab.data.entry_divergence.median_ratio
                  ? `${lab.data.entry_divergence.median_ratio}×`
                  : "—"}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-ink-faint">Median lag to entry</dt>
              <dd className="text-xs tabular-nums text-ink-dim">
                {hours(lab.data.entry_divergence.median_lag_hours) ?? "—"}
              </dd>
            </div>
          </dl>
        </Panel>
      ) : null}

      {/* Findings first: they are the deliverable, and they are drawn only from
          the figures in the table below. */}
      <section className="flex flex-col gap-3">
        <h2 className="text-heading font-medium text-ink">What the replay measured</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {findings.map((finding) => (
            <div
              key={finding.headline}
              className={cn(
                "rounded-card border bg-surface/40 px-4 py-3",
                finding.strategy_id === baseline_id
                  ? "border-plasma/25"
                  : "border-line",
              )}
            >
              <p className="text-sm font-medium text-ink">{finding.headline}</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-dim">
                {finding.detail}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-heading font-medium text-ink">Comparison</h2>
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
                      title={column.hint}
                      aria-pressed={sort === column.key}
                      className={cn(
                        "transition-colors hover:text-ink",
                        sort === column.key && "text-plasma",
                      )}
                    >
                      {column.label}
                    </button>
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-normal">vs benchmark</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => setSelectedId(row.id)}
                  className={cn(
                    "cursor-pointer border-b border-line/60 last:border-0 hover:bg-elevated/40",
                    selected?.id === row.id && "bg-elevated/50",
                  )}
                >
                  <td className="px-3 py-2">
                    <span className="mr-2 tabular-nums text-ink-faint">{row.rank}</span>
                    <span className="text-ink">{row.name}</span>
                    {row.is_baseline ? (
                      <span
                        className="ml-2 rounded-chip border border-plasma/25 bg-plasma/[0.07] px-1.5 py-0.5 text-label uppercase tracking-wide text-plasma"
                        title="The permanent benchmark. Frozen — never tuned in response to this table."
                      >
                        Benchmark
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Value value={row.total_return_pct} signed />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Value value={row.realised_return_pct} signed />
                    {row.open_share_pct && Number(row.open_share_pct) > 0 ? (
                      <span
                        className="ml-1 text-xs text-ink-faint"
                        title={`${row.open_share_pct}% of positions are still open, so the marked figure is a position rather than a result.`}
                      >
                        ({Math.round(Number(row.open_share_pct))}% open)
                      </span>
                    ) : null}
                  </td>
                  {/* Not signed: a win rate is a share, not a gain. "+36%"
                      reads as an improvement on something. */}
                  {/* Net sits beside gross rather than replacing it. The
                      published rules are frozen; this is a cost lens on the
                      same trades, not a restatement of what they were. */}
                  <td className="px-3 py-2 text-right">
                    <Value value={row.net_return_pct} signed />
                    {row.uncosted_trades > 0 ? (
                      <span
                        className="ml-1 text-xs text-ink-faint"
                        title={`${row.uncosted_trades} trades reported no pool depth and are excluded from net.`}
                      >
                        ({row.costed_trades}/{row.costed_trades + row.uncosted_trades})
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Value
                      value={row.win_rate_pct === null ? null : `${row.win_rate_pct}%`}
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Value value={row.max_drawdown_pct === null ? null : `${row.max_drawdown_pct}%`} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Value value={row.profit_factor} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink-dim">
                    {row.closed_count}
                    <span className="text-ink-faint"> / {row.open_count}</span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {row.is_baseline ? (
                      <span className="text-ink-faint" title="A benchmark does not differ from itself">
                        —
                      </span>
                    ) : (
                      <Value value={row.baseline_difference_pct} signed />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-ink-faint">
          Closed / open trades. Win rate, profit factor and drawdown count closed
          trades only, which is why they are shown beside the realised return
          rather than beside the marked one.
        </p>
      </section>

      {selected ? <StrategyDetail strategy={selected} baseline={baseline} /> : null}

      {/* Per-token: where the choice of rule actually mattered. */}
      <section className="flex flex-col gap-3">
        <h2 className="text-heading font-medium text-ink">
          Per token: who captured the move?
        </h2>
        <p className="text-xs text-ink-faint">
          Capture is measured against the peak the token reached while held. A
          token that never rose has no move to capture and crowns nobody.
        </p>
        {tokens.isPending ? (
          <Skeleton className="h-40 rounded-card" />
        ) : (
          <div className="overflow-x-auto rounded-card border border-line">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-line text-label uppercase tracking-wide text-ink-faint">
                  <th className="px-3 py-2 text-left font-normal">Token</th>
                  <th className="px-3 py-2 text-right font-normal">Peak</th>
                  <th className="px-3 py-2 text-right font-normal">Benchmark</th>
                  <th className="px-3 py-2 text-right font-normal">Hold to expiry</th>
                  <th className="px-3 py-2 text-right font-normal">Trailing 25%</th>
                  <th className="px-3 py-2 text-right font-normal">Time 24h</th>
                  <th className="px-3 py-2 text-left font-normal">Captured most</th>
                </tr>
              </thead>
              <tbody>
                {(tokens.data?.items ?? []).slice(0, 40).map((item) => (
                  <tr
                    key={item.mint_address}
                    className="border-b border-line/60 last:border-0 hover:bg-elevated/40"
                  >
                    <td className="px-3 py-2 text-ink">
                      {item.symbol ?? `${item.mint_address.slice(0, 4)}…`}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Value value={item.peak_pct} signed />
                    </td>
                    {["equal_weight_v1", "hold_until_expiry", "trailing_25", "time_24h"].map(
                      (id) => (
                        <td key={id} className="px-3 py-2 text-right">
                          <Value value={item.returns[id] ?? null} signed />
                        </td>
                      ),
                    )}
                    <td className="px-3 py-2 text-xs text-ink-dim">
                      {item.best_strategy_id
                        ? (strategies.find((s) => s.id === item.best_strategy_id)?.name ??
                          item.best_strategy_id)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {unavailable.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-heading font-medium text-ink">Asked for, not measurable</h2>
          {unavailable.map((item) => (
            <Panel key={item.id} density="compact" className="border-line/60">
              <p className="text-sm text-ink">{item.name}</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-dim">{item.reason}</p>
            </Panel>
          ))}
        </section>
      ) : null}
    </div>
  );
}

function StrategyDetail({
  strategy,
  baseline,
}: {
  strategy: LabStrategy;
  baseline: LabStrategy | undefined;
}) {
  const equity = strategy.equity_curve.map((point) => Number(point.equity));
  const drawdown = strategy.equity_curve.map((point) => Number(point.drawdown_pct));
  const returns = strategy.return_distribution.map(Number);
  const holds = strategy.hold_distribution.map(Number);
  const invested = Number(strategy.invested);

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-heading font-medium text-ink">{strategy.name}</h2>
        <p className="text-xs text-ink-faint">
          Select a row above to change this panel
        </p>
      </div>
      <p className="max-w-3xl text-sm text-ink-dim">{strategy.description}</p>

      <dl className="grid gap-x-6 gap-y-2 rounded-card border border-line bg-surface/40 px-4 py-3 sm:grid-cols-2 lg:grid-cols-3">
        {strategy.rules.map((rule) => (
          <div key={rule.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-xs text-ink-faint">{rule.label}</dt>
            <dd className="text-xs tabular-nums text-ink-dim">{rule.value}</dd>
          </div>
        ))}
      </dl>

      <div className="grid gap-3 lg:grid-cols-2">
        <ChartFrame
          title="Equity curve"
          note={`Realised only, after each close. Starts at $${invested.toLocaleString()} invested.`}
        >
          <LineChart
            values={equity}
            baseline={invested}
            tone={
              equity.length > 0 && (equity[equity.length - 1] ?? 0) >= invested
                ? "var(--color-safe)"
                : "var(--color-danger)"
            }
            emptyLabel="No closed trades yet, so there is no realised curve to draw."
          />
        </ChartFrame>

        <ChartFrame
          title="Drawdown"
          note="Fall from the running high of the realised curve. The path between closes is not reconstructed."
        >
          <LineChart
            values={drawdown}
            tone="var(--color-danger)"
            emptyLabel="No closed trades yet, so no drawdown has been measured."
          />
        </ChartFrame>

        <ChartFrame title="Exit reasons" note="Why closed positions ended.">
          <BarChart
            bars={EXIT_ORDER.map((reason) => ({
              label: reason === "target" ? "Target" : reason === "stop" ? "Stop" : "Expiry",
              count: strategy.exits_by_reason[reason] ?? 0,
              tone:
                reason === "target"
                  ? "var(--color-safe)"
                  : reason === "stop"
                    ? "var(--color-danger)"
                    : "var(--color-line-bright)",
            }))}
            emptyLabel="Nothing has closed, so no exit reason has been recorded."
          />
        </ChartFrame>

        <ChartFrame title="Return distribution" note="Per closed trade.">
          <BarChart
            bars={bucket(returns, 6, (low, high) => `${low.toFixed(0)}…${high.toFixed(0)}%`)}
          />
        </ChartFrame>

        <ChartFrame title="Holding time" note="Hours held, per closed trade.">
          <BarChart
            bars={bucket(holds, 6, (low, high) => `${low.toFixed(0)}…${high.toFixed(0)}h`)}
            emptyLabel="Nothing has closed, so no holding time has been measured."
          />
        </ChartFrame>

        <ChartFrame
          title="Peak and giveback"
          note="How high positions got, and how much of it the exit handed back."
        >
          <div className="flex h-full flex-col justify-center gap-3 py-2">
            <div className="flex items-baseline justify-between">
              <span className="text-xs text-ink-faint">Average peak above entry</span>
              <Value value={strategy.average_peak_pct} signed />
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-xs text-ink-faint">Average giveback from peak</span>
              <Value
                value={
                  strategy.average_giveback_pct === null
                    ? null
                    : `${strategy.average_giveback_pct}%`
                }
              />
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-xs text-ink-faint">Average hold</span>
              <span className="tabular-nums text-ink-dim">
                {hours(strategy.average_hold_hours) ?? "—"}
              </span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-ink-faint">
              A high peak with a high giveback means the entries found the move and
              the exit rule did not collect it.
            </p>
          </div>
        </ChartFrame>
      </div>

      {/* Two figures the replay cannot honestly produce over this window. Named
          rather than omitted, so their absence is a fact and not a gap. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Panel density="compact" className="border-line/60">
          <p className="text-label uppercase tracking-wide text-ink-faint">
            Annualised return
          </p>
          <p className="mt-1 text-xs leading-relaxed text-ink-dim">
            {strategy.annualised_unavailable_reason ??
              pct(strategy.annualised_return_pct) ??
              "—"}
          </p>
        </Panel>
        <Panel density="compact" className="border-line/60">
          <p className="text-label uppercase tracking-wide text-ink-faint">
            Monthly returns
          </p>
          <p className="mt-1 text-xs leading-relaxed text-ink-dim">
            Not shown. The replay covers less than one month, so there is no
            month to report — a single partial bucket labelled as a month would
            read as a rate.
          </p>
        </Panel>
      </div>

      {baseline && !strategy.is_baseline ? (
        <p className="text-xs text-ink-faint">
          Equal Weight v1 returned {pct(baseline.total_return_pct) ?? "—"} marked over
          the same detections. It is frozen and is not tuned in response to this
          page.
        </p>
      ) : null}
    </section>
  );
}

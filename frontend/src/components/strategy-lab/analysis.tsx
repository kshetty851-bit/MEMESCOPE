"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  useLabCompare,
  useLabExperiments,
  useLabRugs,
} from "@/hooks/use-strategy-lab";
import {
  FILL_REASON_LABEL,
  multiple,
  shortMint,
  type LabMode,
} from "@/lib/strategy-lab";
import { cn } from "@/lib/utils";

import { DatasetFooter, FlagChips, Money, Percent, SectionNote } from "./shared";

/**
 * TOKEN COMPARE — §14, and the reason the whole design exists.
 *
 * One canonical opportunity, offered to every strategy, so a leaderboard
 * position can be *explained* rather than merely observed. A strategy that
 * refused the token shows why it refused it; a strategy that took it shows
 * every fill in order.
 */
export function TokenCompare({ mode }: { mode: LabMode }) {
  const [input, setInput] = useState("");
  const [mint, setMint] = useState<string | null>(null);
  const { data, isPending, error } = useLabCompare(mint, mode);

  return (
    <div className="space-y-4">
      <Panel density="compact">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setMint(input.trim() || null);
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <div className="min-w-[18rem] flex-1">
            <Input
              label="Mint address"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Paste a mint that became a canonical opportunity"
              spellCheck={false}
            />
          </div>
          <button
            type="submit"
            className="h-9 rounded-md border border-line bg-raised px-4 text-sm font-medium text-ink transition-colors hover:border-accent hover:text-accent"
          >
            Compare
          </button>
        </form>
      </Panel>

      {!mint ? (
        <EmptyState
          title="Compare one token across every strategy"
          body="Paste a mint address to see what each of the twelve strategies did with the same opportunity — including the ones that refused it, and why."
        />
      ) : error ? (
        <ErrorState body="No canonical opportunity is recorded for that mint." />
      ) : isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : data ? (
        <Panel density="flush">
          <PanelHeader className="px-4 pt-4">
            <PanelTitle className="font-mono">{shortMint(data.mint_address)}</PanelTitle>
            <p className="mt-0.5 text-xs text-ink-3">
              Eligible {String(data.opportunity.eligible_at ?? "").slice(0, 16).replace("T", " ")} UTC
              {data.opportunity.venue ? ` · ${String(data.opportunity.venue)}` : null}
            </p>
          </PanelHeader>

          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-4 py-3 text-xs sm:grid-cols-4 lg:grid-cols-6">
            {(
              [
                ["Entry price", data.opportunity.entry_price],
                ["Liquidity", data.opportunity.liquidity_usd],
                ["Market cap", data.opportunity.market_cap],
                ["Radar score", data.opportunity.radar_score],
                ["Confidence", data.opportunity.confidence_score],
                ["Risk band", data.opportunity.risk_band],
                ["SEC-2", data.opportunity.security_status],
                ["Discovery age (h)", data.opportunity.discovery_age_hours],
              ] as [string, unknown][]
            ).map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt className="truncate text-[10px] uppercase tracking-wide text-ink-4">
                  {label}
                </dt>
                <dd className="truncate font-mono text-ink-2">
                  {value === null || value === undefined
                    ? "—"
                    : typeof value === "number"
                      ? value.toLocaleString("en-US", { maximumFractionDigits: 4 })
                      : String(value)}
                </dd>
              </div>
            ))}
          </dl>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr className="border-y border-line bg-raised/40 text-left">
                  <th scope="col" className="px-3 py-2 text-label uppercase text-ink-3">
                    Strategy
                  </th>
                  <th scope="col" className="px-3 py-2 text-right text-label uppercase text-ink-3">
                    Result
                  </th>
                  <th scope="col" className="px-3 py-2 text-right text-label uppercase text-ink-3">
                    Net P&L
                  </th>
                  <th scope="col" className="px-3 py-2 text-right text-label uppercase text-ink-3">
                    Banked early
                  </th>
                  <th scope="col" className="px-3 py-2 text-label uppercase text-ink-3">
                    Lifecycle
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.outcomes.map((outcome) => (
                  <tr
                    key={outcome.strategy_id}
                    className="border-b border-line/60 align-top"
                  >
                    <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-ink">
                      {outcome.strategy_id}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      {outcome.taken ? (
                        <Percent value={outcome.return_pct ?? null} />
                      ) : (
                        <span className="text-xs uppercase text-warn">
                          {(outcome.blocked_reason ?? "").replaceAll("_", " ")}
                        </span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      {outcome.taken ? <Money value={outcome.net_pnl ?? null} signed /> : "—"}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      {outcome.taken ? <Money value={outcome.banked_before_final ?? null} /> : "—"}
                    </td>
                    <td className="px-3 py-2">
                      {outcome.trade ? (
                        <ol className="space-y-0.5 text-xs">
                          <li className="text-ink-3">
                            <span className="font-mono">ENTRY</span>{" "}
                            <Money value={outcome.trade.size_usd} />
                          </li>
                          {outcome.trade.fills.map((fill, index) => (
                            <li key={index} className="text-ink-2">
                              <span className="font-mono">
                                {multiple(fill.multiple)}
                              </span>{" "}
                              <span className="text-ink-3">
                                {FILL_REASON_LABEL[fill.reason] ?? fill.reason}
                              </span>{" "}
                              <span className="font-mono">
                                {fill.quantity_pct_of_initial.toFixed(0)}% sold
                              </span>{" "}
                              → <Money value={fill.net_proceeds} />
                            </li>
                          ))}
                        </ol>
                      ) : (
                        <span className="text-xs text-ink-4">Not taken</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <DatasetFooter dataset={data.dataset} />
        </Panel>
      ) : null}
    </div>
  );
}

/**
 * RUG ANALYSIS — §15.
 *
 * The question the ladder exists to answer: on a token that later collapsed,
 * how much came back on the way up. Recovery is shown per strategy, so
 * "partial profit-taking protects us" is either supported by a number or it is
 * not.
 */
export function RugAnalysis({ mode }: { mode: LabMode }) {
  const { data, isPending, error, refetch } = useLabRugs(mode);

  if (error) {
    return <ErrorState body="Rug analysis could not be loaded." onRetry={() => void refetch()} />;
  }
  if (isPending) return <Skeleton className="h-96 w-full" />;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <SectionNote>{data.definition}</SectionNote>

      <Panel density="flush">
        <PanelHeader className="px-4 pt-4">
          <PanelTitle>Recovery before collapse, by strategy</PanelTitle>
          <p className="mt-0.5 text-xs text-ink-3">
            How much of the capital sunk into catastrophic tokens came back
            before the pool died.
          </p>
        </PanelHeader>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] border-collapse text-sm">
            <thead>
              <tr className="border-y border-line bg-raised/40 text-left">
                {[
                  "Strategy",
                  "Rugs",
                  "Invested",
                  "Recovered before",
                  "Recovery",
                  "Net loss",
                  "≥1.25x",
                  "≥1.50x",
                  "≥1.75x",
                  "≥2x",
                ].map((label, index) => (
                  <th
                    key={label}
                    scope="col"
                    className={cn(
                      "whitespace-nowrap px-3 py-2 text-label uppercase text-ink-3",
                      index > 0 && "text-right",
                    )}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.by_strategy.map((row) => (
                <tr key={row.strategy_id} className="border-b border-line/60">
                  <td className="px-3 py-2">
                    <span className="font-mono font-semibold text-ink">{row.strategy_id}</span>
                    <span className="ml-2 text-xs text-ink-3">{row.name}</span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{row.rugs}</td>
                  <td className="px-3 py-2 text-right">
                    <Money value={row.capital_invested} digits={0} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Money value={row.capital_recovered_before} />
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-up">
                    {row.recovery_pct === null ? "—" : `${row.recovery_pct.toFixed(0)}%`}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Money value={row.net_loss} signed />
                  </td>
                  {[row.reached_125, row.reached_150, row.reached_175, row.reached_200].map(
                    (value, index) => (
                      <td
                        key={index}
                        className="px-3 py-2 text-right font-mono tabular-nums text-ink-2"
                      >
                        {value}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <DatasetFooter dataset={data.dataset} />
      </Panel>

      <Panel density="flush">
        <PanelHeader className="px-4 pt-4">
          <PanelTitle>Catastrophic tokens</PanelTitle>
          <p className="mt-0.5 text-xs text-ink-3">
            Ordered by how far each one ran before it died. Reference path from{" "}
            <span className="font-mono">{data.control_strategy}</span>.
          </p>
        </PanelHeader>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead>
              <tr className="border-y border-line bg-raised/40 text-left">
                {["Token", "Peak (executable)", "Peak (printed)", "Minutes to collapse", "1.25x", "1.50x", "1.75x", "2x"].map(
                  (label, index) => (
                    <th
                      key={label}
                      scope="col"
                      className={cn(
                        "whitespace-nowrap px-3 py-2 text-label uppercase text-ink-3",
                        index > 0 && "text-right",
                      )}
                    >
                      {label}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {data.tokens.map((token) => (
                <tr key={token.mint_address} className="border-b border-line/60">
                  <td className="px-3 py-2 font-mono text-ink-2">
                    {shortMint(token.mint_address)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">
                    {multiple(token.executable_peak_multiple)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-4">
                    {multiple(token.observed_peak_multiple)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                    {token.minutes_to_collapse === null
                      ? "—"
                      : token.minutes_to_collapse.toFixed(0)}
                  </td>
                  {[token.reached_125, token.reached_150, token.reached_175, token.reached_200].map(
                    (reached, index) => (
                      <td
                        key={index}
                        className={cn(
                          "px-3 py-2 text-right font-mono",
                          reached ? "text-up" : "text-ink-4",
                        )}
                      >
                        {reached ? "✓" : "—"}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

/**
 * EXPERIMENTS — §16, §19 and §24.
 *
 * The robustness table is the important half. §24 is mandatory because earlier
 * MEMESCOPE research was distorted by a right tail that turned out not to be
 * real, so "what is left without the best trade" is shown beside every headline
 * rather than on request.
 */
export function Experiments({ mode }: { mode: LabMode }) {
  const { data, isPending, error, refetch } = useLabExperiments(mode);

  if (error) {
    return <ErrorState body="Experiments could not be loaded." onRetry={() => void refetch()} />;
  }
  if (isPending) return <Skeleton className="h-96 w-full" />;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <div className="grid gap-2 lg:grid-cols-2">
        <SectionNote>{data.sampling.in_sample}</SectionNote>
        <SectionNote>{data.sampling.anti_overfitting}</SectionNote>
      </div>

      <Panel density="flush">
        <PanelHeader className="px-4 pt-4">
          <PanelTitle>Robustness — results with the best trades removed</PanelTitle>
          <p className="mt-0.5 text-xs text-ink-3">
            If profitability disappears after removing one token, the strategy is
            flagged rather than ranked on.
          </p>
        </PanelHeader>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse text-sm">
            <thead>
              <tr className="border-y border-line bg-raised/40 text-left">
                {[
                  "Strategy",
                  "N",
                  "Normal",
                  "Ex best 1",
                  "Ex best 3",
                  "Ex worst 1",
                  "Ex worst 3",
                  "Top 1 share",
                  "Top 3 share",
                  "Top 5 share",
                ].map((label, index) => (
                  <th
                    key={label}
                    scope="col"
                    className={cn(
                      "whitespace-nowrap px-3 py-2 text-label uppercase text-ink-3",
                      index > 0 && "text-right",
                    )}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.robustness.map((row) => (
                <tr key={row.strategy_id} className="border-b border-line/60">
                  <td className="px-3 py-2">
                    <span className="font-mono font-semibold text-ink">{row.strategy_id}</span>
                    <div className="mt-0.5">
                      <FlagChips flags={row.flags} />
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{row.n}</td>
                  {[
                    row.normal_pnl,
                    row.ex_best_1_pnl,
                    row.ex_best_3_pnl,
                    row.ex_worst_1_pnl,
                    row.ex_worst_3_pnl,
                  ].map((value, index) => (
                    <td key={index} className="px-3 py-2 text-right">
                      <Money value={value} signed />
                    </td>
                  ))}
                  {[row.top_1_share_pct, row.top_3_share_pct, row.top_5_share_pct].map(
                    (value, index) => (
                      <td
                        key={index}
                        className={cn(
                          "px-3 py-2 text-right font-mono tabular-nums",
                          value !== null && value >= 50 ? "text-warn" : "text-ink-2",
                        )}
                      >
                        {value === null ? "—" : `${value.toFixed(0)}%`}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel density="flush">
        <PanelHeader className="px-4 pt-4">
          <PanelTitle>Market regime by day</PanelTitle>
          <p className="mt-0.5 text-xs text-ink-3">Regime definition v{data.regime.version}</p>
        </PanelHeader>
        <div className="px-4 pb-3 pt-2">
          <SectionNote>{data.regime.definition}</SectionNote>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <thead>
              <tr className="border-y border-line bg-raised/40 text-left">
                {["Day", "Opportunities", "Catastrophe rate", "Label"].map((label, index) => (
                  <th
                    key={label}
                    scope="col"
                    className={cn(
                      "px-3 py-2 text-label uppercase text-ink-3",
                      index > 0 && index < 3 && "text-right",
                    )}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.regime.days.map((day) => (
                <tr key={day.day} className="border-b border-line/60">
                  <td className="px-3 py-2 font-mono text-ink-2">{day.day}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">
                    {day.opportunities}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-down">
                    {day.catastrophe_rate_pct.toFixed(0)}%
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-ink-3">{day.label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <DatasetFooter dataset={data.dataset} />
      </Panel>
    </div>
  );
}

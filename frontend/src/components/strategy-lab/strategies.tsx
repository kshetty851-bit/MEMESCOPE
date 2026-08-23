"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Tooltip } from "@/components/ui/tooltip";
import { useLabLeaderboard, useLabStrategies } from "@/hooks/use-strategy-lab";
import {
  plain,
  shortMint,
  type LabMode,
  type LabRow,
  type LabStrategyDefinition,
} from "@/lib/strategy-lab";
import { cn } from "@/lib/utils";

import { FlagChips, Money, Percent, SectionNote, SimulatedBadge } from "./shared";

/**
 * STRATEGY CARDS.
 *
 * One card per strategy, showing what its own simulated $1,000 did. Every
 * balance carries the SIMULATED marker — the brief's hard requirement, and the
 * one thing on this page that must never be ambiguous.
 *
 * The rule itself is rendered as a ladder rather than as prose, because the
 * whole comparison is about *which* rungs a strategy takes and the numbers say
 * that faster than a sentence.
 */

function ruleSummary(definition: LabStrategyDefinition): string[] {
  const parts: string[] = [`$${definition.entry_size_usd.toFixed(0)} entry`];
  if (definition.rungs.length) {
    parts.push(
      definition.rungs
        .map((r) => `${(r.fraction * 100).toFixed(0)}% @ ${r.multiple.toFixed(2)}x`)
        .join(" · "),
    );
  }
  if (definition.runner_fraction > 0) {
    parts.push(`${(definition.runner_fraction * 100).toFixed(0)}% runner`);
  }
  if (definition.trailing) {
    parts.push(
      definition.trailing.activation_multiple === null
        ? `${(definition.trailing.drawdown * 100).toFixed(0)}% trail from entry`
        : `${(definition.trailing.drawdown * 100).toFixed(0)}% trail after ${definition.trailing.activation_multiple.toFixed(2)}x`,
    );
  }
  for (const decay of definition.decay) {
    parts.push(
      `exit at ${decay.at_minutes.toFixed(0)}m if never ≥${decay.never_exceeded.toFixed(2)}x and ≤${decay.at_or_below.toFixed(2)}x`,
    );
  }
  if (definition.min_discovery_age_hours !== null) {
    parts.push(`entry gate: discovery age ≥ ${definition.min_discovery_age_hours}h`);
  }
  parts.push(`${definition.hold_hours}h hard expiry`);
  if (!definition.rungs.length && !definition.trailing && !definition.decay.length) {
    parts.splice(1, 0, "no stop, no target, no trail");
  }
  return parts;
}

function StrategyCard({
  definition,
  row,
  onSelect,
}: {
  definition: LabStrategyDefinition;
  row: LabRow | undefined;
  onSelect: () => void;
}) {
  return (
    <Panel density="compact" className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <button type="button" onClick={onSelect} className="group text-left">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-md font-semibold text-ink group-hover:text-accent">
              {definition.strategy_id}
            </span>
            <span className="text-xs text-ink-3">v{definition.version}</span>
            {definition.benchmark ? (
              <span className="rounded-sm border border-line px-1 py-px text-[10px] uppercase text-ink-3">
                Legacy baseline
              </span>
            ) : null}
          </span>
          <p className="mt-0.5 text-sm text-ink-2 group-hover:text-ink">{definition.name}</p>
        </button>
        <SimulatedBadge />
      </div>

      <ul className="space-y-0.5 text-xs text-ink-3">
        {ruleSummary(definition).map((line) => (
          <li key={line} className="truncate">
            {line}
          </li>
        ))}
      </ul>

      {row ? (
        <>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-line pt-3 text-xs sm:grid-cols-3">
            <Field label="Simulated cash">
              <Money value={row.final_equity} />
            </Field>
            <Field label="Simulated equity">
              <Money value={row.final_equity} />
            </Field>
            <Field label="Return">
              <Percent value={row.wallet_return_pct} />
            </Field>
            <Field label="Closed">
              <span className="font-mono tabular-nums">{row.n}</span>
            </Field>
            <Field label="Open">
              <span className="font-mono tabular-nums">0</span>
            </Field>
            <Field label="P&L">
              <Money value={row.net_pnl} signed />
            </Field>
            <Field label="Profit factor">
              <span className="font-mono tabular-nums">
                {row.profit_factor === null ? "∞" : plain(row.profit_factor)}
              </span>
            </Field>
            <Field label="Expectancy">
              <Money value={row.expectancy} signed />
            </Field>
            <Field label="Max drawdown">
              <span className="font-mono tabular-nums text-down">
                {row.max_drawdown_pct.toFixed(1)}%
              </span>
            </Field>
            <Field label="Rug losses">
              <Money value={-Math.abs(row.rug_loss_usd)} signed />
            </Field>
            <Field label="Capital blocked">
              <Money value={row.capital_blocked_usd} digits={0} />
            </Field>
            <Field label="2x / 5x / 10x">
              <span className="font-mono tabular-nums">
                {row.moonshots.map((m) => m.captured).join(" / ")}
              </span>
            </Field>
          </dl>
          <FlagChips flags={row.flags} />
        </>
      ) : (
        <p className="border-t border-line pt-3 text-xs text-ink-3">
          No results recorded for this strategy yet.
        </p>
      )}

      <Tooltip content={definition.definition_hash} side="top">
        <p className="cursor-help truncate font-mono text-[10px] text-ink-4">
          hash {shortMint(definition.definition_hash)}
        </p>
      </Tooltip>
    </Panel>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-[10px] uppercase tracking-wide text-ink-4">{label}</dt>
      <dd className="truncate">{children}</dd>
    </div>
  );
}

export function StrategyGrid({
  mode,
  onSelect,
}: {
  mode: LabMode;
  onSelect: (id: string) => void;
}) {
  const definitions = useLabStrategies();
  const board = useLabLeaderboard(mode, "ALL");

  if (definitions.error) {
    return (
      <ErrorState
        body="Strategy definitions could not be loaded."
        onRetry={() => void definitions.refetch()}
      />
    );
  }

  const rows = new Map((board.data?.rows ?? []).map((r) => [r.strategy_id, r]));

  return (
    <div className="space-y-4">
      {definitions.data ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <SectionNote>{definitions.data.notes.multi_target}</SectionNote>
          <SectionNote>{definitions.data.notes.s9_gate}</SectionNote>
        </div>
      ) : null}

      {definitions.isPending ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-64 w-full" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {definitions.data?.strategies.map((definition) => (
            <StrategyCard
              key={`${definition.strategy_id}@${definition.version}`}
              definition={definition}
              row={rows.get(definition.strategy_id)}
              onSelect={() => onSelect(definition.strategy_id)}
            />
          ))}
        </div>
      )}

      {definitions.data ? <ExperimentMatrix strategies={definitions.data.strategies} /> : null}
    </div>
  );
}

/** §21's comparison matrix, derived from the definitions rather than typed. */
export function ExperimentMatrix({
  strategies,
}: {
  strategies: LabStrategyDefinition[];
}) {
  const columns = [
    ["entry_25", "$25 entry"],
    ["no_initial_stop", "No initial stop"],
    ["partial_profits", "Partial profits"],
    ["expiry_6h", "6h expiry"],
    ["runner", "Runner"],
    ["survival_gate", "Survival gate"],
    ["time_decay", "Time decay"],
    ["trailing", "Trailing"],
  ] as const;

  return (
    <Panel density="flush">
      <PanelHeader className="px-4 pt-4">
        <PanelTitle>Experiment matrix</PanelTitle>
        <p className="mt-0.5 text-xs text-ink-3">
          Derived from each definition, so it cannot drift from the code.
        </p>
      </PanelHeader>
      <div className="overflow-x-auto px-4 pb-4 pt-3">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <th scope="col" className="py-2 pr-3 text-label uppercase text-ink-3">
                Property
              </th>
              {strategies.map((s) => (
                <th
                  key={s.strategy_id}
                  scope="col"
                  className="px-2 py-2 text-center font-mono text-label text-ink-3"
                >
                  {s.strategy_id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {columns.map(([key, label]) => (
              <tr key={key} className="border-b border-line/50">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink-2">
                  {label}
                </th>
                {strategies.map((s) => (
                  <td
                    key={s.strategy_id}
                    className={cn(
                      "px-2 py-1.5 text-center font-mono",
                      s.matrix[key] ? "text-up" : "text-ink-4",
                    )}
                  >
                    {s.matrix[key] ? "✓" : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

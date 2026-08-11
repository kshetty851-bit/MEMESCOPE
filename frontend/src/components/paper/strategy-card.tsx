"use client";

import { Label, Panel } from "@/components/ui/panel";
import type { PaperStrategy } from "@/types/paper";

/**
 * THE PUBLISHED RULE
 *
 * The reason the wallet's numbers mean anything. Without the rule stated in
 * advance, "the simulation made 40%" is indistinguishable from a claim — with
 * it, a reader can check any trade in the positions table against the rule that
 * produced it.
 *
 * Rendered from what the backend serves, which is derived from the same fields
 * the simulation applies. The published rule and the executed rule cannot
 * drift, and a test asserts it.
 */
export function StrategyCard({ strategy }: { strategy: PaperStrategy }) {
  return (
    <Panel density="compact" className="border-line-subtle">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <Label>The rule</Label>
          <p className="mt-1 text-md font-medium text-ink">
            {strategy.name}{" "}
            <span className="text-xs font-normal text-ink-3">v{strategy.version}</span>
          </p>
        </div>
        {!strategy.operational && strategy.unavailable_reason ? (
          <span className="rounded-sm border border-line px-2 py-0.5 text-label uppercase tracking-wide text-ink-3">
            Not running
          </span>
        ) : null}
      </div>

      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">
        {strategy.summary}
      </p>

      <dl className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
        {strategy.rules.map((rule) => (
          <div key={rule.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-xs text-ink-3">{rule.label}</dt>
            <dd className="text-xs tabular-nums text-ink-2">{rule.value}</dd>
          </div>
        ))}
      </dl>

      {strategy.unavailable_reason ? (
        <p className="mt-3 text-xs text-ink-3">{strategy.unavailable_reason}</p>
      ) : null}
    </Panel>
  );
}

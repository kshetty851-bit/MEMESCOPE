"use client";

import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";

import { EquityChart } from "./charts";
import { dec, pct, signedDec, utcDate, noteText, count } from "./format";
import { FlagBadges, GenericValue, KeyValues, RecordTable, Section } from "./generic";
import { RobustnessSections } from "./robustness";
import { RunStatus } from "./run-status";
import { TargetPanel } from "./targets";
import type { BacktestSummary, Coded, RunDetail, Scorecard, Window } from "./types";

const span = (w: Window) => `${utcDate(w.start)} to ${utcDate(w.end)}`;

function PeriodCard({
  title,
  caption,
  summary,
  testId,
}: {
  title: string;
  caption: string;
  summary: BacktestSummary;
  testId: string;
}) {
  const m = summary.metrics;
  return (
    <Section title={title} hint={caption} testId={testId}>
      <p className="mb-3 text-xs text-ink-3">{span(summary.window)}</p>
      <div className="grid grid-cols-2 gap-3">
        <Stat
          boxed
          size="sm"
          label="Net return"
          display={pct(m.net_return_pct, { signed: true })}
          signed
          value={m.net_return_pct}
        />
        <Stat boxed size="sm" label="Trades" display={count(summary.trade_count)} />
        <Stat boxed size="sm" label="Win rate" display={pct(m.win_rate_pct)} />
        <Stat
          boxed
          size="sm"
          label="Profit factor"
          display={m.profit_factor === null ? null : dec(m.profit_factor)}
        />
        <Stat
          boxed
          size="sm"
          label="Expectancy (R)"
          display={m.expectancy_r === null ? null : signedDec(m.expectancy_r)}
        />
        <Stat boxed size="sm" label="Max drawdown" display={pct(m.max_drawdown_pct)} />
        <Stat
          boxed
          size="sm"
          label="Sharpe"
          display={m.sharpe === null ? "not meaningful" : dec(m.sharpe)}
          hint={m.sharpe === null ? noteText(m.sharpe_note) : undefined}
        />
      </div>
      <div className="mt-3">
        <EquityChart points={summary.equity_curve} startingBalance={m.starting_balance} />
      </div>
    </Section>
  );
}

export function ScorecardView({ card }: { card: Scorecard }) {
  return (
    <Section title="Scorecard" testId="scorecard">
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <Stat
          label="Robustness score"
          display={card.robustness_score === null ? null : dec(card.robustness_score, 0)}
        />
        <div className="flex max-w-[70ch] flex-col gap-1">
          <span className="text-label font-medium uppercase text-ink-3">Verdict</span>
          <span className="text-sm" data-testid="verdict">
            {card.verdict.text}
          </span>
        </div>
      </div>
      <FlagBadges flags={card.flags} />
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        {(["full", "out_of_sample", "stressed", "stability"] as const).map((key) => (
          <div key={key}>
            <h3 className="mb-2 text-label font-medium uppercase text-ink-3">
              {key === "out_of_sample"
                ? "Out of sample"
                : key === "full"
                  ? "Full period"
                  : key === "stressed"
                    ? "Stressed costs"
                    : "Stability"}
            </h3>
            <KeyValues data={card[key]} />
          </div>
        ))}
      </div>
    </Section>
  );
}

/** A research result: dev/validation/test, optimisation, robustness checks. */
export function ResearchView({
  detail,
  disclaimer,
}: {
  detail: RunDetail;
  disclaimer?: Coded | null;
}) {
  const { run, result } = detail;
  if (!result || result.type !== "research") return <RunStatus run={run} />;
  const r = result;
  const best = r.optimisation.best;

  return (
    <div className="flex flex-col gap-4" data-testid="research-view">
      <Section title="Split windows" testId="split">
        <div className="grid gap-3 text-sm md:grid-cols-3">
          {(
            [
              ["Development", r.split.development],
              ["Validation", r.split.validation],
              ["Test", r.split.test],
            ] as const
          ).map(([label, w]) => (
            <div key={label} className="rounded-md border border-line px-3 py-2">
              <div className="text-label font-medium uppercase text-ink-3">{label}</div>
              <div data-numeric>{span(w)}</div>
            </div>
          ))}
        </div>
      </Section>

      <div className="grid gap-4 xl:grid-cols-3" data-testid="period-cards">
        <PeriodCard
          title="Development"
          caption="Parameters were searched here."
          summary={r.development}
          testId="period-development"
        />
        <PeriodCard
          title="Validation"
          caption="Used to compare the candidates the search produced."
          summary={r.validation}
          testId="period-validation"
        />
        <div>
          <PeriodCard
            title="Test"
            caption="Untouched until this run; never used for selection."
            summary={r.test}
            testId="period-test"
          />
        </div>
      </div>

      <Section
        title="Optimisation grid"
        hint="Development window only."
        testId="optimisation"
      >
        {r.selection_note ? (
          <p className="mb-3 text-sm text-ink-2" data-testid="selection-note">
            {r.selection_note.text}
          </p>
        ) : null}
        <div className="mb-3 flex flex-col gap-1">
          <span className="text-label font-medium uppercase text-ink-3">
            Chosen parameters
          </span>
          <KeyValues data={r.chosen_params} />
        </div>
        {best ? (
          <p className="mb-3 flex items-center gap-2 text-xs text-ink-3">
            <Badge tone="plasma">Best on development</Badge>
            <span>{JSON.stringify(best)}</span>
          </p>
        ) : null}
        <RecordTable rows={r.optimisation.rows} caption="Optimisation grid rows" />
      </Section>

      <Section title="Walk-forward" testId="walk-forward">
        <RecordTable rows={r.walk_forward.folds} caption="Walk-forward folds" />
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div>
            <h3 className="mb-1 text-label font-medium uppercase text-ink-3">
              Out-of-sample summary
            </h3>
            <GenericValue value={r.walk_forward.oos_summary} name="oos_summary" />
          </div>
          <div>
            <h3 className="mb-1 text-label font-medium uppercase text-ink-3">Efficiency</h3>
            <GenericValue value={r.walk_forward.efficiency} name="efficiency" />
          </div>
        </div>
      </Section>

      <Section title="Parameter sensitivity" testId="sensitivity">
        <div className="flex flex-col gap-4">
          {Object.entries(r.sensitivity).map(([path, rows]) => (
            <div key={path}>
              <h3 className="mb-1 text-label font-medium uppercase text-ink-3">{path}</h3>
              <RecordTable rows={rows} caption={`Sensitivity of ${path}`} />
            </div>
          ))}
        </div>
      </Section>

      <Section title="Stability" testId="stability">
        <GenericValue value={r.stability} name="stability" />
      </Section>

      <Section
        title="Cost stress"
        hint="The same trades re-priced at higher costs."
        testId="cost-stress"
      >
        <RecordTable rows={r.cost_stress} caption="Cost stress" />
      </Section>

      <Section title="Market regimes" testId="regimes">
        <RecordTable rows={r.regimes} caption="Results by regime" />
      </Section>

      <RobustnessSections
        baseline={r.baseline}
        monteCarlo={r.monte_carlo}
        bootstrap={r.bootstrap}
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <TargetPanel
          title="Monthly targets, full period"
          report={r.targets.full}
          disclaimer={disclaimer}
          testId="target-full"
        />
        <TargetPanel
          title="Monthly targets, out of sample"
          report={r.targets.out_of_sample}
          disclaimer={disclaimer}
          testId="target-oos"
        />
      </div>

      <ScorecardView card={r.scorecard} />
    </div>
  );
}

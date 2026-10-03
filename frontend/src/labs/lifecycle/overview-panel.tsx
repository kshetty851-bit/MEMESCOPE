import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Stat, StatRow } from "@/components/ui/stat";

import {
  DataClassLabel,
  Figure,
  formatPlainUsd,
  formatRatioPct,
  formatSignedUsd,
  formatUtc,
  humanize,
} from "./display";
import type { ExperimentSplit, LifecycleOverview } from "./types";

/** "no_forward_run_yet" reads as the plain sentence the board wants. */
function unavailableSentence(reason: string): string {
  if (reason === "no_forward_run_yet") return "No forward replay yet";
  const text = humanize(reason);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function Split({ experiment }: { experiment: ExperimentSplit }) {
  const rows: Array<[string, [string, string]]> = [
    ["Train", experiment.train],
    ["Validation", experiment.validation],
    ["Test", experiment.test],
  ];
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-label font-medium uppercase text-ink-3">
          Experiment split
        </span>
        <span className="text-xs text-ink-2" data-numeric>
          {experiment.experiment_key}
        </span>
        {experiment.split_meaningful ? null : (
          <Badge tone="warn">split not yet meaningful</Badge>
        )}
      </div>
      <dl className="grid gap-2 sm:grid-cols-3">
        {rows.map(([name, [from, to]]) => (
          <div key={name} className="rounded-md border border-line px-3 py-2">
            <dt className="text-label uppercase text-ink-3">{name}</dt>
            <dd data-numeric className="text-xs text-ink-2">
              {formatUtc(from)} → {formatUtc(to)}
            </dd>
          </div>
        ))}
      </dl>
      <p className="max-w-[70ch] text-xs text-ink-3">{experiment.split_note}</p>
    </div>
  );
}

export function OverviewPanel({ overview }: { overview: LifecycleOverview }) {
  const p = overview.portfolio;
  const why = p.unavailable_reason;

  return (
    <Panel>
      <PanelHeader>
        <div className="flex flex-col gap-1">
          <PanelTitle>Lab overview — $1,000 paper account</PanelTitle>
          <p className="text-xs text-ink-3">
            {p.as_of ? `As of ${formatUtc(p.as_of)}` : "No ledger snapshot yet"}
            {p.run_id ? ` · run ${p.run_id.slice(0, 8)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <DataClassLabel
            dataClass={overview.mode === "exploratory" ? "exploratory" : "authoritative"}
          />
          <Badge tone="neutral">{p.sample_label}</Badge>
        </div>
      </PanelHeader>

      {why ? (
        <p
          role="status"
          className="mb-4 rounded-md border border-line bg-sunken px-3 py-2 text-sm text-ink-2"
        >
          {unavailableSentence(why)}
        </p>
      ) : null}

      <StatRow className="grid-cols-2 md:grid-cols-4">
        <Stat label="Starting capital">
          <Figure value={p.starting_capital} format={formatPlainUsd} />
        </Stat>
        <Stat label="Equity">
          <Figure value={p.equity} format={formatPlainUsd} reason={why} />
        </Stat>
        <Stat label="Realized P&L">
          <Figure value={p.realized_pnl} format={formatSignedUsd} reason={why} />
        </Stat>
        <Stat label="Unrealized P&L">
          <Figure value={p.unrealized_pnl} format={formatSignedUsd} reason={why} />
        </Stat>
        <Stat label="ROI">
          <Figure value={p.roi} format={formatRatioPct} reason={why} />
        </Stat>
        <Stat label="Drawdown">
          <Figure value={p.drawdown} format={formatRatioPct} reason={why} />
        </Stat>
        <Stat label="Paper trades" value={p.trades} display={String(p.trades)} />
        <Stat
          label="Open positions"
          value={p.open_positions}
          display={String(p.open_positions)}
        />
      </StatRow>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-1">
          <span className="text-label font-medium uppercase text-ink-3">
            Forward observation
          </span>
          <span className="text-sm text-ink" data-numeric>
            {overview.forward_start
              ? `Since ${formatUtc(overview.forward_start)}`
              : "Not started"}
          </span>
          <span className="text-xs text-ink-3" data-numeric>
            {overview.forward_days === null
              ? "Days of forward data: unavailable"
              : `${overview.forward_days.toFixed(1)} days of forward data`}
          </span>
        </div>
        <div className="flex gap-6">
          <Stat
            label="Tracked memes"
            value={overview.tracked_memes}
            display={String(overview.tracked_memes)}
          />
          <Stat
            label="Linked tokens"
            value={overview.linked_tokens}
            display={String(overview.linked_tokens)}
          />
        </div>
      </div>

      {overview.experiment ? (
        <div className="mt-5">
          <Split experiment={overview.experiment} />
        </div>
      ) : (
        <p className="mt-5 text-xs text-ink-3">
          No experiment registered — split boundaries unavailable.
        </p>
      )}

      {overview.notes.length > 0 ? (
        <ul className="mt-5 flex flex-col gap-1 border-t border-line-subtle pt-3 text-xs text-ink-3">
          {overview.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

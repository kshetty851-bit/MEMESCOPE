"use client";

import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Tabs } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";
import {
  BLOCK_LABEL,
  DISCOVERY_BLOCKS,
  DISCOVERY_FLAG_MEANING,
  STATUS_TONE,
  fetchDiscoveryAttribution,
  fetchDiscoveryCandidates,
  fetchDiscoveryChampions,
  fetchDiscoveryOverview,
  fetchDiscoverySpace,
  type DiscoveryBlock,
  type DiscoveryDataset,
  type DiscoveryRow,
} from "@/lib/strategy-discovery";
import { cn } from "@/lib/utils";

import { Money, Percent, SectionNote } from "./shared";

/**
 * STRATEGY DISCOVERY — §27.
 *
 * A funnel, a search space, a candidate table, and champions. The funnel is the
 * important part: it makes visible how much of a 1,850-strategy search survives
 * contact with data it was not designed on, and "nothing did" is a legitimate
 * and useful outcome that this screen is built to state plainly.
 *
 * Nothing here starts a search. There is no button that could.
 */

const DISCOVERY_POLL_MS = 300_000;

type Section = "overview" | "space" | "candidates" | "champions" | "attribution";

const SECTIONS: { value: Section; label: string }[] = [
  { value: "overview", label: "Search overview" },
  { value: "space", label: "Search space" },
  { value: "candidates", label: "Candidates" },
  { value: "champions", label: "Champions" },
  { value: "attribution", label: "Feature attribution" },
];

function useOverview(dataset: DiscoveryDataset) {
  return useQuery({
    queryKey: ["discovery", "overview", dataset],
    queryFn: () => fetchDiscoveryOverview(dataset),
    refetchInterval: DISCOVERY_POLL_MS,
  });
}

function FlagChips({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {flags.map((flag) => (
        <Tooltip key={flag} content={DISCOVERY_FLAG_MEANING[flag] ?? flag} side="top">
          <span className="inline-flex cursor-help items-center rounded-sm border border-warn/35 bg-warn/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-warn">
            {flag.replaceAll("_", " ")}
          </span>
        </Tooltip>
      ))}
    </span>
  );
}

/** §27's funnel. Rendered as bars so a collapse to zero is visible, not read. */
function Funnel({
  funnel,
}: {
  funnel: { generated: number; discovery_survivors: number; validation_survivors: number; holdout_survivors: number; champions: number };
}) {
  const steps = [
    { label: "Generated", value: funnel.generated, note: "bounded search space" },
    { label: "Discovery survivors", value: funnel.discovery_survivors, note: "in-sample, top 15%" },
    { label: "Validation survivors", value: funnel.validation_survivors, note: "out-of-sample filters" },
    { label: "Holdout survivors", value: funnel.holdout_survivors, note: "sealed block, opened once" },
    { label: "Forward champions", value: funnel.champions, note: "meet every research standard" },
  ];
  const max = Math.max(...steps.map((s) => s.value), 1);

  return (
    <ol className="space-y-2">
      {steps.map((step, index) => (
        <li key={step.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-ink-2">{step.label}</span>
            <span
              className={cn(
                "font-mono tabular-nums",
                step.value === 0 ? "text-down" : "text-ink",
              )}
            >
              {step.value.toLocaleString("en-US")}
            </span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-raised">
            <div
              className={cn(
                "h-full rounded-full",
                step.value === 0 ? "bg-down/50" : "bg-accent/60",
              )}
              style={{ width: `${Math.max((step.value / max) * 100, step.value ? 1 : 0)}%` }}
            />
          </div>
          <p className="mt-0.5 text-[11px] text-ink-4">
            {step.note}
            {index > 0 && steps[index - 1]!.value > 0
              ? ` · ${((step.value / steps[index - 1]!.value) * 100).toFixed(1)}% of the step above`
              : null}
          </p>
        </li>
      ))}
    </ol>
  );
}

function Overview({ dataset }: { dataset: DiscoveryDataset }) {
  const { data, isPending, error, refetch } = useOverview(dataset);

  if (error) {
    return <ErrorState body="The search could not be loaded." onRetry={() => void refetch()} />;
  }
  if (isPending) return <Skeleton className="h-96 w-full" />;
  if (!data?.has_run) {
    return (
      <SectionNote>
        No search has been recorded for this dataset yet. A search is run by an
        operator on the host — it evaluates thousands of definitions and is
        deliberately not startable from this page.
      </SectionNote>
    );
  }

  const split = data.split;
  const diagnosis = split?.diagnosis;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel density="comfortable">
          <PanelTitle>Funnel</PanelTitle>
          <div className="mt-3">{data.funnel ? <Funnel funnel={data.funnel} /> : null}</div>
        </Panel>

        <div className="space-y-3">
          <Panel density="compact">
            <PanelTitle>Dataset</PanelTitle>
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
              <Field label="Source">{data.dataset_source}</Field>
              <Field label="Usable opportunities">{data.universe_usable}</Field>
              <Field label="Runtime">
                {data.runtime_seconds ? `${data.runtime_seconds.toFixed(1)}s` : "—"}
              </Field>
              <Field label="Schedule resolutions">
                {(data.schedule_resolutions ?? 0).toLocaleString("en-US")}
              </Field>
              <Field label="Engine / space / scoring">
                {`v${data.engine_version} / v${data.space_version} / v${data.scoring_version}`}
              </Field>
              <Field label="Walk-forward folds">{split?.walk_forward_folds ?? "—"}</Field>
            </dl>
            {data.exclusions && Object.keys(data.exclusions).length ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(data.exclusions).map(([reason, count]) => (
                  <Badge key={reason} tone="neutral">
                    <span className="font-mono">{count}</span>
                    <span className="lowercase">{reason.replaceAll("_", " ")}</span>
                  </Badge>
                ))}
              </div>
            ) : null}
          </Panel>

          <Panel density="compact">
            <PanelTitle>Chronological split</PanelTitle>
            <p className="mt-0.5 text-xs text-ink-3">
              Granularity: <span className="font-mono">{split?.granularity}</span>
            </p>
            <dl className="mt-2 space-y-1 text-xs">
              {(["discovery", "validation", "holdout"] as const).map((block) => (
                <div key={block} className="flex items-baseline justify-between gap-2">
                  <dt className="uppercase tracking-wide text-ink-4">{block}</dt>
                  <dd className="text-right font-mono text-ink-2">
                    {split?.sizes[block] ?? 0} ·{" "}
                    {split?.[block].from?.slice(5, 16).replace("T", " ") ?? "—"} →{" "}
                    {split?.[block].to?.slice(5, 16).replace("T", " ") ?? "—"}
                  </dd>
                </div>
              ))}
            </dl>
          </Panel>
        </div>
      </div>

      {diagnosis?.warnings?.length ? (
        <Panel density="compact" className="border-warn/40">
          <PanelTitle className="text-warn">What limits this search</PanelTitle>
          <ul className="mt-2 space-y-1.5 text-sm leading-relaxed text-ink-2">
            {diagnosis.warnings.map((warning) => (
              <li key={warning}>• {warning}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-3">
            {diagnosis.calendar_days} calendar day(s) in the sample;{" "}
            {diagnosis.substantial_days} carry a meaningful share; the largest
            holds {diagnosis.largest_day_share_pct.toFixed(0)}%.
          </p>
        </Panel>
      ) : null}

      {data.ranking ? <SectionNote>{data.ranking}</SectionNote> : null}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-[10px] uppercase tracking-wide text-ink-4">{label}</dt>
      <dd className="truncate font-mono text-ink-2">{children}</dd>
    </div>
  );
}

function SearchSpace({ dataset }: { dataset: DiscoveryDataset }) {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["discovery", "space", dataset],
    queryFn: () => fetchDiscoverySpace(dataset),
    staleTime: Infinity,
  });

  if (error) {
    return <ErrorState body="The search space could not be loaded." onRetry={() => void refetch()} />;
  }
  if (isPending) return <Skeleton className="h-96 w-full" />;
  if (!data) return null;

  const groups: [string, { key: string; label: string; rule: string }[]][] = [
    ["Entry", data.entries],
    ["Profit taking", data.profits],
    ["Exit / hold", data.exits],
    ["Portfolio (second stage)", data.portfolios],
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2">
        {groups.map(([title, rows]) => (
          <Panel key={title} density="compact">
            <PanelTitle>{title}</PanelTitle>
            <ul className="mt-2 space-y-1.5 text-xs">
              {rows.map((row) => (
                <li key={row.key}>
                  <span className="font-mono text-ink-2">{row.key}</span>
                  <span className="ml-2 text-ink-3">{row.rule}</span>
                </li>
              ))}
            </ul>
          </Panel>
        ))}
      </div>

      <Panel density="compact">
        <PanelTitle>Position sizes</PanelTitle>
        <p className="mt-1 text-sm text-ink-2">
          {data.sizes.map((s) => `$${s}`).join(" · ")}
          <span className="ml-2 text-ink-4">
            (plus ${data.legacy_size} as a legacy reference, ranked apart)
          </span>
        </p>
      </Panel>

      <Panel density="compact" className="border-warn/40">
        <PanelTitle className="text-warn">Requested but not testable</PanelTitle>
        <p className="mt-1 text-xs text-ink-3">
          Each of these was checked against the live dataset. None is a
          preference.
        </p>
        <ul className="mt-2 space-y-1.5 text-xs">
          {Object.entries(data.unavailable_features).map(([feature, why]) => (
            <li key={feature}>
              <span className="font-mono text-ink-2">{feature}</span>
              <span className="ml-2 text-ink-3">{why}</span>
            </li>
          ))}
        </ul>
      </Panel>

      {data.notes.map((note) => (
        <SectionNote key={note}>{note}</SectionNote>
      ))}
    </div>
  );
}

const COLUMNS = [
  "#",
  "Strategy",
  "Entry",
  "Size",
  "TP",
  "Exit",
  "N",
  "Capture",
  "OOS return",
  "PF",
  "Expectancy",
  "Max DD",
  "Rug loss",
  "2x ret.",
  "5x ret.",
  "Profitable days",
  "Outlier",
  "Status",
];

function CandidateTable({ dataset }: { dataset: DiscoveryDataset }) {
  const [block, setBlock] = useState<DiscoveryBlock>("WALK_FORWARD");
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["discovery", "candidates", dataset, block],
    queryFn: () => fetchDiscoveryCandidates(dataset, block),
    refetchInterval: DISCOVERY_POLL_MS,
  });

  return (
    <Panel density="flush">
      <PanelHeader className="px-4 pt-4">
        <PanelTitle>Candidates</PanelTitle>
        <p className="mt-0.5 text-xs text-ink-3">{BLOCK_LABEL[block]}</p>
        <div
          role="group"
          aria-label="Evaluation block"
          className="mt-2 flex flex-wrap gap-1 rounded-md border border-line bg-raised/50 p-1"
        >
          {DISCOVERY_BLOCKS.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setBlock(value)}
              aria-pressed={value === block}
              className={cn(
                "rounded-sm px-2.5 py-1 text-label font-medium transition-colors",
                value === block ? "bg-surface text-ink shadow-e1" : "text-ink-3 hover:text-ink",
              )}
            >
              {value.replaceAll("_", " ")}
            </button>
          ))}
        </div>
      </PanelHeader>

      {error ? (
        <ErrorState body="Candidates could not be loaded." onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="space-y-2 px-4 pb-4 pt-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : !data?.rows.length ? (
        <p className="px-4 pb-6 pt-3 text-sm text-ink-3">
          No candidate reached this block.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1500px] border-collapse text-sm">
            <thead>
              <tr className="border-y border-line bg-raised/40 text-left">
                {COLUMNS.map((label, index) => (
                  <th
                    key={label}
                    scope="col"
                    className={cn(
                      "whitespace-nowrap px-3 py-2 text-label font-semibold uppercase tracking-wide text-ink-3",
                      index >= 6 && index <= 15 && "text-right",
                    )}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <CandidateRow key={row.strategy_id} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function CandidateRow({ row }: { row: DiscoveryRow }) {
  return (
    <tr className="border-b border-line/60 transition-colors hover:bg-raised/40">
      <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-3">{row.rank}</td>
      <td className="px-3 py-2">
        <Tooltip content={row.explanation} side="top">
          <span className="cursor-help font-mono font-semibold text-ink">
            {row.strategy_id}
          </span>
        </Tooltip>
        <div className="mt-0.5">
          <FlagChips flags={row.flags} />
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-ink-3">
        {row.entry_rules}
      </td>
      <td className="px-3 py-2 font-mono text-xs text-ink-3">{row.size}</td>
      <td className="px-3 py-2 font-mono text-xs text-ink-3">{row.profit}</td>
      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-ink-3">{row.exit}</td>
      <td className="px-3 py-2 text-right font-mono tabular-nums">{row.n}</td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
        {row.capture_pct === null ? "—" : `${row.capture_pct.toFixed(0)}%`}
      </td>
      <td className="px-3 py-2 text-right">
        <Percent value={row.return_pct} />
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums">
        {row.profit_factor === null ? "—" : row.profit_factor.toFixed(2)}
      </td>
      <td className="px-3 py-2 text-right">
        <Money value={row.expectancy} signed />
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-down">
        {row.max_drawdown_pct === null ? "—" : `${row.max_drawdown_pct.toFixed(1)}%`}
      </td>
      <td className="px-3 py-2 text-right">
        <Money value={row.rug_loss_usd === null ? null : -Math.abs(row.rug_loss_usd)} signed />
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
        {row.retention_2x === null ? "—" : `${row.retention_2x.toFixed(0)}%`}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
        {row.retention_5x === null ? "—" : `${row.retention_5x.toFixed(0)}%`}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
        {row.profitable_day_pct === null ? "—" : `${row.profitable_day_pct.toFixed(0)}%`}
      </td>
      <td className="px-3 py-2 text-center font-mono text-xs">
        {row.outlier_dependent_top3 ? (
          <span className="text-down">top 3</span>
        ) : row.outlier_dependent ? (
          <span className="text-warn">top 1</span>
        ) : (
          <span className="text-ink-4">—</span>
        )}
      </td>
      <td className="px-3 py-2">
        <Badge tone={STATUS_TONE[row.status]}>{row.status}</Badge>
      </td>
    </tr>
  );
}

function Champions({ dataset }: { dataset: DiscoveryDataset }) {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["discovery", "champions", dataset],
    queryFn: () => fetchDiscoveryChampions(dataset),
    refetchInterval: DISCOVERY_POLL_MS,
  });

  if (error) {
    return <ErrorState body="Champions could not be loaded." onRetry={() => void refetch()} />;
  }
  if (isPending) return <Skeleton className="h-64 w-full" />;
  if (!data?.has_run) {
    return <SectionNote>No search has been recorded for this dataset yet.</SectionNote>;
  }

  return (
    <div className="space-y-4">
      <Panel density="comfortable">
        <PanelTitle>Verdict</PanelTitle>
        <p
          className={cn(
            "mt-1 font-mono text-lg",
            data.champions.length ? "text-up" : "text-warn",
          )}
        >
          {data.verdict}
        </p>
        {data.next_step ? (
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-3">
            {data.next_step}
          </p>
        ) : null}
      </Panel>

      <Panel density="compact">
        <PanelTitle>Research standards</PanelTitle>
        <p className="mt-0.5 text-xs text-ink-3">
          All must hold. These are research standards, not production rules.
        </p>
        <ul className="mt-2 grid gap-1 text-xs text-ink-2 sm:grid-cols-2">
          {(data.standards ?? []).map((standard) => (
            <li key={standard}>• {standard}</li>
          ))}
        </ul>
      </Panel>

      {data.champions.length ? (
        <div className="grid gap-3 md:grid-cols-2">
          {data.champions.map((champion) => (
            <Panel key={champion.strategy_id} density="compact">
              <span className="font-mono text-md font-semibold text-ink">
                {champion.strategy_id}
              </span>
              <p className="mt-1 text-sm leading-relaxed text-ink-2">
                {champion.explanation}
              </p>
            </Panel>
          ))}
        </div>
      ) : (
        <SectionNote>
          No candidate met every standard. That is an acceptable outcome and is
          reported as one — a search that always produces a winner is a search
          that has fitted its own dataset.
        </SectionNote>
      )}
    </div>
  );
}

function Attribution({ dataset }: { dataset: DiscoveryDataset }) {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["discovery", "attribution", dataset],
    queryFn: () => fetchDiscoveryAttribution(dataset),
    refetchInterval: DISCOVERY_POLL_MS,
  });

  if (error) {
    return <ErrorState body="Attribution could not be loaded." onRetry={() => void refetch()} />;
  }
  if (isPending) return <Skeleton className="h-96 w-full" />;
  if (!data?.has_run) {
    return <SectionNote>No search has been recorded for this dataset yet.</SectionNote>;
  }

  return (
    <div className="space-y-4">
      {data.caveat ? <SectionNote>{data.caveat}</SectionNote> : null}
      {Object.entries(data.dimensions).map(([dimension, levels]) => (
        <Panel key={dimension} density="flush">
          <PanelHeader className="px-4 pt-4">
            <PanelTitle>{dimension.replaceAll("_", " ")}</PanelTitle>
          </PanelHeader>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <thead>
                <tr className="border-y border-line bg-raised/40 text-left">
                  {["Level", "Strategies", "Mean return", "Median return", "Mean PF", "Mean capture", "Survived"].map(
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
                {levels.map((level) => (
                  <tr key={level.level} className="border-b border-line/60">
                    <td className="px-3 py-2 font-mono text-ink-2">{level.level}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-3">
                      {level.n_strategies}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Percent value={Number(level.mean_return_pct)} />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Percent value={Number(level.median_return_pct)} />
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {level.mean_profit_factor === null
                        ? "—"
                        : Number(level.mean_profit_factor).toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {Number(level.mean_capture_pct).toFixed(0)}%
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-2">
                      {level.survivors} ({Number(level.survival_pct).toFixed(0)}%)
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ))}
    </div>
  );
}

export function StrategyDiscovery() {
  const [section, setSection] = useState<Section>("overview");
  const [dataset, setDataset] = useState<DiscoveryDataset>("LOCAL_BACKTEST");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm leading-relaxed text-ink-3">
          An automated walk-forward search over a bounded family of strategy
          definitions, all replayed against the same canonical opportunity
          stream. It optimises for surviving data it was not designed on, and it
          recommends only — it cannot activate anything.
        </p>
        <div
          role="group"
          aria-label="Dataset source"
          className="flex gap-1 rounded-md border border-line bg-raised/50 p-1"
        >
          {(["LOCAL_BACKTEST", "PRODUCTION_FORWARD_RESEARCH"] as DiscoveryDataset[]).map(
            (value) => (
              <button
                key={value}
                type="button"
                onClick={() => setDataset(value)}
                aria-pressed={value === dataset}
                className={cn(
                  "rounded-sm px-3 py-1 text-label font-medium transition-colors",
                  value === dataset ? "bg-surface text-ink shadow-e1" : "text-ink-3 hover:text-ink",
                )}
              >
                {value === "LOCAL_BACKTEST" ? "Local backtest" : "Production forward"}
              </button>
            ),
          )}
        </div>
      </div>

      <Tabs
        aria-label="Discovery sections"
        value={section}
        onChange={setSection}
        items={SECTIONS}
      />

      {section === "overview" ? <Overview dataset={dataset} /> : null}
      {section === "space" ? <SearchSpace dataset={dataset} /> : null}
      {section === "candidates" ? <CandidateTable dataset={dataset} /> : null}
      {section === "champions" ? <Champions dataset={dataset} /> : null}
      {section === "attribution" ? <Attribution dataset={dataset} /> : null}
    </div>
  );
}

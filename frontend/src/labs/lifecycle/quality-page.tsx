"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Absent } from "@/components/ui/num";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Stat, StatRow } from "@/components/ui/stat";
import { ErrorState } from "@/components/ui/states";
import { shortenAddress } from "@/lib/format";

import { DataBoundaryBanner } from "./data-boundary-banner";
import {
  Figure,
  PaperOnlyBanner,
  StatusPill,
  Unavailable,
  agoFromIso,
  formatNumber,
  formatPlainPct,
  formatUtc,
  humanize,
} from "./display";
import { useLifecycleQuality } from "./hooks";
import type {
  QualityReport,
  SourceCollectionStats,
} from "./types";

/**
 * DATA QUALITY — is the forward dataset trustworthy yet?
 *
 * Counts here are real counts, so a zero is a genuine zero. Rates are the
 * opposite: a rate with nothing to divide (null) is "unavailable", never 0%.
 * Forward and backfill are always shown apart, each under its boundary banner.
 */

function count(n: number): string {
  return formatNumber(String(n));
}

function SplitStat({
  label,
  split,
}: {
  label: string;
  split: { forward: number; backfill: number };
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-line p-3">
      <span className="text-label font-medium uppercase text-ink-3">{label}</span>
      <div className="grid grid-cols-2 gap-3">
        <Stat
          label="Forward"
          display={count(split.forward)}
          value={split.forward}
          hint="eligible for the verdict"
        />
        <Stat
          label="Backfill"
          display={count(split.backfill)}
          value={split.backfill}
          hint="exploratory"
        />
      </div>
    </div>
  );
}

function SourceTable({ rows }: { rows: SourceCollectionStats[] }) {
  return (
    <Panel density="flush">
      <PanelHeader className="mb-0 p-4 pb-3">
        <PanelTitle>Collection by source (24h)</PanelTitle>
      </PanelHeader>
      {rows.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-ink-3">No collection runs reported.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-sm">
            <caption className="sr-only">Collection runs and outcomes per source over 24 hours</caption>
            <thead>
              <tr className="border-y border-line bg-sunken text-left text-label uppercase text-ink-3">
                <th scope="col" className="px-4 py-2 font-medium">Source</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Runs</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Available</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Unavailable</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Disabled</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Error</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Stale</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Partial</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Success rate</th>
                <th scope="col" className="px-3 py-2 font-medium">Last success</th>
                <th scope="col" className="px-3 py-2 font-medium">Last status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.source}
                  data-testid={`quality-source-${r.source}`}
                  className="border-b border-line-subtle"
                >
                  <th scope="row" className="px-4 py-2 text-left font-medium text-ink">{r.label}</th>
                  {[r.runs_24h, r.available, r.unavailable, r.disabled, r.error, r.stale, r.partial].map(
                    (n, i) => (
                      <td key={i} className="px-3 py-2 text-right tabular-nums" data-numeric>
                        {count(n)}
                      </td>
                    ),
                  )}
                  <td className="px-3 py-2 text-right">
                    <Figure
                      value={r.success_rate_24h}
                      format={formatPlainPct}
                      reason="no_countable_runs"
                    />
                  </td>
                  <td className="px-3 py-2 text-ink-2" data-numeric>
                    {r.last_success_at ? (
                      <>
                        {formatUtc(r.last_success_at)}
                        <span className="block text-xs text-ink-3">{agoFromIso(r.last_success_at)}</span>
                      </>
                    ) : (
                      "never"
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {r.last_status ? (
                      <div className="flex flex-col items-start gap-1">
                        <StatusPill status={r.last_status} />
                        {r.last_reason ? (
                          <span className="text-xs text-ink-3">{humanize(r.last_reason)}</span>
                        ) : null}
                      </div>
                    ) : (
                      <Unavailable reason="no_runs_recorded" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function SourceNames({ title, names }: { title: string; names: string[] }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-label font-medium uppercase text-ink-3">{title}</span>
      {names.length === 0 ? (
        <span className="text-sm text-ink-3">none</span>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {names.map((n) => (
            <Badge key={n} tone="warn">{n}</Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function GapList({
  title,
  empty,
  testId,
  children,
  isEmpty,
}: {
  title: string;
  empty: string;
  testId: string;
  isEmpty: boolean;
  children: ReactNode;
}) {
  return (
    <Panel data-testid={testId}>
      <PanelHeader>
        <PanelTitle>{title}</PanelTitle>
      </PanelHeader>
      {isEmpty ? <p className="text-sm text-ink-3">{empty}</p> : children}
    </Panel>
  );
}

function memeLink(slug: string, label?: string) {
  return (
    <Link href={`/lifecycle-lab/${encodeURIComponent(slug)}`} className="text-accent hover:underline">
      {label ?? slug}
    </Link>
  );
}

export function QualityReportView({ report }: { report: QualityReport }) {
  const c = report.collection;
  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <Link href="/lifecycle-lab" className="text-xs text-accent hover:underline">
          ← Meme Lifecycle Lab
        </Link>
        <h1 className="text-xl font-semibold">Data quality</h1>
        <p className="max-w-[70ch] text-sm text-ink-2">
          What the lab has actually collected, how often collection succeeded, and
          where the record has gaps. Generated {formatUtc(report.generated_at)}.
        </p>
        <PaperOnlyBanner />
      </header>

      <Panel>
        <PanelHeader>
          <PanelTitle>Observations</PanelTitle>
        </PanelHeader>
        <StatRow className="mb-4 grid-cols-2">
          <Stat label="Tracked memes" value={report.tracked_memes} display={count(report.tracked_memes)} />
          <Stat label="Tracked tokens" value={report.tracked_tokens} display={count(report.tracked_tokens)} />
        </StatRow>
        <div className="grid gap-3 md:grid-cols-2">
          <SplitStat label="Today" split={report.observations_today} />
          <SplitStat label="Last 7 days" split={report.observations_week} />
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-2" data-testid="quality-boundary">
          <DataBoundaryBanner kind="forward" />
          <DataBoundaryBanner kind="exploratory" />
        </div>
        <dl className="mt-4 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-label uppercase text-ink-3">Oldest forward observation</dt>
            <dd data-numeric data-testid="oldest-forward">
              {report.oldest_forward_observation_at ? (
                formatUtc(report.oldest_forward_observation_at)
              ) : (
                <Unavailable reason="no_forward_observations" />
              )}
            </dd>
          </div>
          <div>
            <dt className="text-label uppercase text-ink-3">Newest forward observation</dt>
            <dd data-numeric data-testid="newest-forward">
              {report.newest_forward_observation_at ? (
                <>
                  {formatUtc(report.newest_forward_observation_at)}{" "}
                  <span className="text-xs text-ink-3">
                    {agoFromIso(report.newest_forward_observation_at)}
                  </span>
                </>
              ) : (
                <Unavailable reason="no_forward_observations" />
              )}
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel>
        <PanelHeader>
          <PanelTitle>Collection (24h)</PanelTitle>
        </PanelHeader>
        <StatRow className="grid-cols-3">
          <Stat label="Runs" value={c.runs_24h} display={count(c.runs_24h)} />
          <Stat label="Failures" value={c.failures_24h} display={count(c.failures_24h)} />
          <Stat label="Success rate">
            <span data-testid="collection-success-rate">
              <Figure value={c.success_rate_24h} format={formatPlainPct} reason="no_countable_runs" />
            </span>
          </Stat>
        </StatRow>
        <p className="mt-3 max-w-[70ch] text-xs text-ink-3">
          Success rate is available runs divided by runs that were not disabled.
          A disabled source is a configuration choice, not a failure, and is left
          out of both sides.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <SourceNames title="Unavailable sources" names={report.unavailable_sources} />
          <SourceNames title="Stale sources" names={report.stale_sources} />
        </div>
      </Panel>

      <SourceTable rows={c.by_source} />

      <div className="grid gap-6 lg:grid-cols-3">
        <GapList
          title="Memes without observations"
          testId="gap-memes"
          empty="Every tracked meme has at least one observation."
          isEmpty={report.memes_without_observations.length === 0}
        >
          <ul className="flex flex-col gap-1.5 text-sm">
            {report.memes_without_observations.map((m) => (
              <li key={m.slug}>{memeLink(m.slug, m.display_name)}</li>
            ))}
          </ul>
        </GapList>

        <GapList
          title="Tokens without market history"
          testId="gap-tokens"
          empty="Every linked token has market history."
          isEmpty={report.tokens_without_market_history.length === 0}
        >
          <ul className="flex flex-col gap-1.5 text-sm">
            {report.tokens_without_market_history.map((t) => (
              <li key={`${t.meme_slug}-${t.mint}`} className="flex flex-wrap gap-x-2">
                <span data-numeric>{shortenAddress(t.mint, 6, 6)}</span>
                {memeLink(t.meme_slug)}
              </li>
            ))}
          </ul>
        </GapList>

        <GapList
          title="Tokens with incomplete market data"
          testId="gap-incomplete"
          empty="No linked token is missing market fields."
          isEmpty={report.tokens_with_incomplete_market_data.length === 0}
        >
          <ul className="flex flex-col gap-2 text-sm">
            {report.tokens_with_incomplete_market_data.map((t) => (
              <li key={`${t.meme_slug}-${t.mint}`} className="flex flex-col gap-1">
                <span className="flex flex-wrap gap-x-2">
                  <span data-numeric>{shortenAddress(t.mint, 6, 6)}</span>
                  {memeLink(t.meme_slug)}
                </span>
                <span className="flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
                  missing:
                  {t.missing.length === 0 ? (
                    <Absent label="no fields listed" />
                  ) : (
                    t.missing.map((f) => (
                      <Badge key={f} tone="warn">{humanize(f)}</Badge>
                    ))
                  )}
                </span>
              </li>
            ))}
          </ul>
        </GapList>
      </div>
    </div>
  );
}

export function LifecycleQualityPage() {
  const { data, isLoading, isError, refetch } = useLifecycleQuality();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <PaperOnlyBanner />
        <ErrorState
          title="Could not load the data-quality report"
          body="The quality endpoint did not answer."
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  return <QualityReportView report={data} />;
}

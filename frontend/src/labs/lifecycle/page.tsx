"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { shortenAddress } from "@/lib/format";

import { AuditTrail } from "./audit-trail";
import { DataBoundaryBanner, boundaryKinds } from "./data-boundary-banner";
import { DataHealthPanel } from "./data-health-panel";
import {
  PaperOnlyBanner,
  agoFromIso,
  formatConfidence,
  formatUtc,
  humanize,
} from "./display";
import { EventsTable } from "./events-table";
import {
  useLifecycleHealth,
  useLifecycleMeme,
  useLifecycleMemes,
  useLifecycleOverview,
  useResearchStatus,
} from "./hooks";
import { MiniSeries } from "./mini-series";
import { LifecycleOverlayChart } from "./overlay-chart";
import { OverviewPanel } from "./overview-panel";
import { RadarTable } from "./radar-table";
import { ResearchStatusPanel } from "./research-status-panel";
import { TradesPanel } from "./trades-panel";
import type { LifecycleOverview, MemeDetail } from "./types";

/**
 * MEME LIFECYCLE LAB
 *
 * A measurement board: does a meme already living on the internet, in a
 * measurable new attention wave with market confirmation, carry information the
 * market signals do not? The page reports what was observed and ranks nothing.
 *
 * Everything shown is computed on the backend; the client converts strings to
 * numbers only to print them. Nothing here applies a threshold, estimates a
 * missing value, or words an observation as advice.
 */

/**
 * The overview carries `research_status`; GET /research-status is only asked
 * for when an older overview response lacks it, so the panel is never silently
 * absent. While neither has answered, nothing is drawn rather than a guess.
 */
function ResearchStatusSection({ overview }: { overview: LifecycleOverview }) {
  const fallback = useResearchStatus(!overview.research_status);
  const status = overview.research_status ?? fallback.data;
  if (!status) return null;
  return <ResearchStatusPanel status={status} />;
}

export function LifecycleLabPage() {
  const overview = useLifecycleOverview();
  const health = useLifecycleHealth();
  const memes = useLifecycleMemes();

  if (overview.isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (overview.isError || !overview.data) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <PaperOnlyBanner />
        <ErrorState
          title="Could not load the Meme Lifecycle Lab"
          body="The overview endpoint did not answer."
          onRetry={() => void overview.refetch()}
        />
      </div>
    );
  }

  const data = overview.data;

  if (!data.lab_enabled) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <PaperOnlyBanner />
        <ResearchStatusSection overview={data} />
        <EmptyState
          title="The Meme Lifecycle Lab is not enabled"
          body="FEATURE_LIFECYCLE_LAB_ENABLED is off, so nothing is being collected. This is not the same as the lab running and finding nothing."
        />
      </div>
    );
  }

  // /health is the fresher source; the overview's summary is the fallback so
  // the panel is never blank while it loads or if only that call fails.
  const sources = health.data?.sources ?? data.sources;

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">Meme Lifecycle Lab</h1>
        <p className="max-w-[70ch] text-sm text-ink-2">
          Memes that already exist on the internet, matched to tokens, with
          attention and market activity on one clock. The lab records what
          changed and when it was detected; it ranks nothing.
        </p>
        <PaperOnlyBanner />
        <Link
          href="/lifecycle-lab/quality"
          className="w-fit text-sm text-accent hover:underline"
        >
          Data quality →
        </Link>
      </header>

      <ResearchStatusSection overview={data} />
      <OverviewPanel overview={data} />
      <DataHealthPanel sources={sources} />

      {memes.isError ? (
        <ErrorState
          title="Could not load the meme radar"
          body="The memes endpoint did not answer."
          onRetry={() => void memes.refetch()}
        />
      ) : (
        <RadarTable rows={memes.data?.items ?? []} isPending={memes.isLoading} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

function IdentityPanel({ detail }: { detail: MemeDetail }) {
  const { meme, aliases, links } = detail;
  return (
    <Panel>
      <PanelHeader>
        <div className="flex flex-col gap-1">
          <PanelTitle>Identity and token links</PanelTitle>
          {meme.description ? (
            <p className="max-w-[70ch] text-sm text-ink-2">{meme.description}</p>
          ) : null}
        </div>
      </PanelHeader>

      <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-label uppercase text-ink-3">Tracking started</dt>
          <dd data-numeric>{formatUtc(meme.tracking_started_at)}</dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Wikipedia article</dt>
          <dd>{meme.wikipedia_title ?? <span className="text-ink-3">none configured</span>}</dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">News query (GDELT)</dt>
          <dd data-numeric>{meme.gdelt_query ?? <span className="text-ink-3">none configured</span>}</dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Aliases</dt>
          <dd className="flex flex-wrap gap-1.5">
            {aliases.length === 0 ? (
              <span className="text-ink-3">none</span>
            ) : (
              aliases.map((a) => (
                <Badge key={`${a.alias}-${a.kind}`} tone="neutral">
                  {a.alias}
                  <span className="text-ink-3">{humanize(a.kind)}</span>
                </Badge>
              ))
            )}
          </dd>
        </div>
      </dl>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">Tokens linked to this meme</caption>
          <thead>
            <tr className="border-y border-line bg-sunken text-left text-label uppercase text-ink-3">
              <th scope="col" className="px-3 py-2 font-medium">Token</th>
              <th scope="col" className="px-3 py-2 font-medium">Method</th>
              <th scope="col" className="px-3 py-2 font-medium">Confidence</th>
              <th scope="col" className="px-3 py-2 font-medium">Linked at</th>
              <th scope="col" className="px-3 py-2 font-medium">Unlinked</th>
            </tr>
          </thead>
          <tbody>
            {links.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-ink-3">
                  No token is linked to this meme yet.
                </td>
              </tr>
            ) : (
              links.map((l) => (
                <tr key={l.mint} className="border-b border-line-subtle">
                  <td className="px-3 py-2" data-numeric>{shortenAddress(l.mint, 6, 6)}</td>
                  <td className="px-3 py-2 text-ink-2">{humanize(l.method)}</td>
                  <td className="px-3 py-2" data-numeric>{formatConfidence(l.confidence)}</td>
                  {/* linked_at is the fact the point-in-time gate keys on: the
                      link is invisible to every decision before this instant. */}
                  <td className="px-3 py-2">
                    <span data-numeric className="font-semibold text-ink">
                      {formatUtc(l.linked_at)}
                    </span>
                    <span className="block text-xs text-ink-3">
                      visible to the lab only after this instant · {agoFromIso(l.linked_at)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-ink-3" data-numeric>
                    {l.unlinked_at ? formatUtc(l.unlinked_at) : "still linked"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function MemeDetailView({ detail }: { detail: MemeDetail }) {
  const { series } = detail;
  const perSource = Object.entries(series.per_source ?? {});

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <Link href="/lifecycle-lab" className="text-xs text-accent hover:underline">
          ← Meme Lifecycle Lab
        </Link>
        <h1 className="text-xl font-semibold">{detail.meme.display_name}</h1>
        <PaperOnlyBanner />
      </header>

      <div data-testid="data-label-banner" className="flex flex-col gap-2">
        {boundaryKinds(detail.data_label, detail.contains_backfill).map((kind) => (
          <DataBoundaryBanner key={kind} kind={kind} />
        ))}
      </div>

      <IdentityPanel detail={detail} />

      <Panel>
        <PanelHeader>
          <PanelTitle>Attention, price and volume</PanelTitle>
        </PanelHeader>
        <LifecycleOverlayChart series={series} markers={detail.markers} />
      </Panel>

      {perSource.length > 0 ? (
        <section aria-label="Per-source attention series" className="flex flex-col gap-3">
          <h2 className="text-md font-medium tracking-tight text-ink">By source</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {perSource.map(([source, points]) => (
              <MiniSeries
                key={source}
                source={source}
                points={points}
                backfillBefore={series.backfill_before}
              />
            ))}
          </div>
        </section>
      ) : null}

      <EventsTable events={detail.events} />
      <TradesPanel trades={detail.trades} />
      <DataHealthPanel sources={detail.sources} title="Sources for this meme" />
      <AuditTrail slug={detail.meme.slug} />
    </div>
  );
}

export function LifecycleMemeDetailPage({ slug }: { slug: string }) {
  const { data, isLoading, isError, error, refetch } = useLifecycleMeme(slug);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-72 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    const notFound = (error as { status?: number } | null)?.status === 404;
    return (
      <div className="flex flex-col gap-4 p-6">
        <PaperOnlyBanner />
        {notFound ? (
          <EmptyState
            title="No such meme"
            body={`Nothing is tracked under "${slug}".`}
            action={
              <Link href="/lifecycle-lab" className="text-sm text-accent hover:underline">
                Back to the radar
              </Link>
            }
          />
        ) : (
          <ErrorState
            title="Could not load this meme"
            body="The meme endpoint did not answer."
            onRetry={() => void refetch()}
          />
        )}
      </div>
    );
  }

  return <MemeDetailView detail={data} />;
}

/** Route-level wrapper: reads the slug from the URL. */
export function LifecycleMemeDetailRoute() {
  const params = useParams<{ slug: string }>();
  return <LifecycleMemeDetailPage slug={params.slug} />;
}

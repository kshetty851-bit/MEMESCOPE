"use client";

import { Badge } from "@/components/ui/badge";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { shortenAddress } from "@/lib/format";

import { DataBoundaryBanner } from "./data-boundary-banner";
import {
  MeasuredValue,
  StatusPill,
  Unavailable,
  agoFromIso,
  formatConfidence,
  formatInterval,
  formatMultiple,
  formatNumber,
  formatUtc,
  humanize,
} from "./display";
import { useLifecycleMemeQuality } from "./hooks";
import type { LinkEvidence, MemeQuality } from "./types";

/**
 * AUDIT TRAIL — how this meme got into the dataset and what was collected for it.
 *
 * Every figure is stated with its provenance (who linked it, by what method, at
 * what confidence, from what evidence). Nothing is derived here; missing is
 * shown as missing.
 */

function Evidence({ evidence }: { evidence: LinkEvidence }) {
  if (evidence === null || evidence === undefined || evidence === "") {
    return <span className="text-ink-3">none recorded</span>;
  }
  if (typeof evidence === "string") return <span>{evidence}</span>;
  if (Array.isArray(evidence)) {
    return <span data-numeric>{JSON.stringify(evidence)}</span>;
  }
  const entries = Object.entries(evidence);
  if (entries.length === 0) return <span className="text-ink-3">none recorded</span>;
  return (
    <dl className="flex flex-col gap-0.5">
      {entries.map(([k, v]) => (
        <div key={k} className="flex flex-wrap gap-x-1.5">
          <dt className="text-ink-3">{humanize(k)}:</dt>
          <dd data-numeric>{typeof v === "string" ? v : JSON.stringify(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th scope="col" className={`px-3 py-2 font-medium ${right ? "text-right" : ""}`}>
      {children}
    </th>
  );
}

const HEAD = "border-y border-line bg-sunken text-left text-label uppercase text-ink-3";

function Sub({ title }: { title: string }) {
  return <h3 className="mb-2 mt-5 text-label font-medium uppercase text-ink-3">{title}</h3>;
}

export function AuditTrailView({ audit }: { audit: MemeQuality }) {
  const { meme } = audit;
  const hasBackfill = audit.sources.some((s) => s.backfill_count > 0);
  const priority = audit.collection_priority;

  return (
    <Panel data-testid="audit-trail">
      <PanelHeader>
        <div className="flex flex-col gap-1">
          <PanelTitle>Audit trail</PanelTitle>
          <p className="max-w-[70ch] text-xs text-ink-3">
            Identity, token links, and what has been collected for this meme, with
            provenance.
          </p>
        </div>
      </PanelHeader>

      <Sub title="Identity" />
      <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-label uppercase text-ink-3">Slug</dt>
          <dd data-numeric>{meme.slug}</dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Display name</dt>
          <dd>{meme.display_name}</dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Tracking started</dt>
          <dd data-numeric>{formatUtc(meme.tracking_started_at)}</dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">News query (GDELT)</dt>
          <dd data-numeric>{meme.gdelt_query ?? <span className="text-ink-3">none configured</span>}</dd>
        </div>
      </dl>

      <Sub title="Aliases" />
      {audit.aliases.length === 0 ? (
        <p className="text-sm text-ink-3">No aliases.</p>
      ) : (
        <ul className="flex flex-wrap gap-2" data-testid="audit-aliases">
          {audit.aliases.map((a) => (
            <li key={`${a.alias}-${a.kind}`}>
              <Badge tone="neutral">
                {a.alias}
                <span className="text-ink-3">{humanize(a.kind)}</span>
                <span className="text-ink-3" data-numeric>
                  added {formatUtc(a.added_at)}
                </span>
              </Badge>
            </li>
          ))}
        </ul>
      )}

      <Sub title="Token links" />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <caption className="sr-only">Token links with method, confidence and evidence</caption>
          <thead>
            <tr className={HEAD}>
              <Th>Token</Th>
              <Th>Method</Th>
              <Th>Confidence</Th>
              <Th>Linked at</Th>
              <Th>Unlinked at</Th>
              <Th>Linked by</Th>
              <Th>Evidence</Th>
            </tr>
          </thead>
          <tbody>
            {audit.links.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-ink-3">No token has been linked.</td>
              </tr>
            ) : (
              audit.links.map((l) => (
                <tr key={`${l.mint}-${l.linked_at}`} className="border-b border-line-subtle align-top">
                  <td className="px-3 py-2" data-numeric>{shortenAddress(l.mint, 6, 6)}</td>
                  <td className="px-3 py-2 text-ink-2">{humanize(l.method)}</td>
                  <td className="px-3 py-2" data-numeric>{formatConfidence(l.confidence)}</td>
                  <td className="px-3 py-2" data-numeric>
                    {formatUtc(l.linked_at)}
                    <span className="block text-xs text-ink-3">{agoFromIso(l.linked_at)}</span>
                  </td>
                  <td className="px-3 py-2 text-ink-3" data-numeric>
                    {l.unlinked_at ? formatUtc(l.unlinked_at) : "still linked"}
                  </td>
                  <td className="px-3 py-2 text-ink-2">
                    {l.linked_by ?? <span className="text-ink-3">not recorded</span>}
                  </td>
                  <td className="px-3 py-2 text-xs text-ink-2">
                    <Evidence evidence={l.evidence} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Sub title="Observations by source" />
      {hasBackfill ? (
        <div className="mb-3 grid gap-3 lg:grid-cols-2">
          <DataBoundaryBanner kind="forward" />
          <DataBoundaryBanner kind="exploratory" />
        </div>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-sm">
          <caption className="sr-only">First and latest observation per source</caption>
          <thead>
            <tr className={HEAD}>
              <Th>Source</Th>
              <Th>Status</Th>
              <Th>First</Th>
              <Th>Latest</Th>
              <Th right>Total</Th>
              <Th right>Forward</Th>
              <Th right>Backfill</Th>
            </tr>
          </thead>
          <tbody>
            {audit.sources.map((s) => (
              <tr
                key={s.source}
                data-testid={`audit-source-${s.source}`}
                className="border-b border-line-subtle"
              >
                <th scope="row" className="px-3 py-2 text-left font-medium text-ink">{s.label}</th>
                <td className="px-3 py-2">
                  <div className="flex flex-col items-start gap-1">
                    <StatusPill status={s.status} />
                    {s.reason ? <span className="text-xs text-ink-3">{humanize(s.reason)}</span> : null}
                  </div>
                </td>
                <td className="px-3 py-2 text-ink-2" data-numeric>
                  {s.first_observation_at ? formatUtc(s.first_observation_at) : <Unavailable reason="no_observations" />}
                </td>
                <td className="px-3 py-2 text-ink-2" data-numeric>
                  {s.latest_observation_at ? formatUtc(s.latest_observation_at) : <Unavailable reason="no_observations" />}
                </td>
                <td className="px-3 py-2 text-right" data-numeric>{formatNumber(String(s.observation_count))}</td>
                <td className="px-3 py-2 text-right" data-numeric>{formatNumber(String(s.forward_count))}</td>
                <td className="px-3 py-2 text-right" data-numeric>{formatNumber(String(s.backfill_count))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Sub title="Market data by token" />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <caption className="sr-only">Market observation coverage per linked token</caption>
          <thead>
            <tr className={HEAD}>
              <Th>Token</Th>
              <Th>First</Th>
              <Th>Latest</Th>
              <Th right>Observations</Th>
              <Th>Missing fields</Th>
            </tr>
          </thead>
          <tbody>
            {audit.market.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-ink-3">No market data collected.</td>
              </tr>
            ) : (
              audit.market.map((mk) => (
                <tr key={mk.mint} className="border-b border-line-subtle">
                  <td className="px-3 py-2" data-numeric>{shortenAddress(mk.mint, 6, 6)}</td>
                  <td className="px-3 py-2 text-ink-2" data-numeric>
                    {mk.first_observation_at ? formatUtc(mk.first_observation_at) : <Unavailable reason="no_observations" />}
                  </td>
                  <td className="px-3 py-2 text-ink-2" data-numeric>
                    {mk.latest_observation_at ? formatUtc(mk.latest_observation_at) : <Unavailable reason="no_observations" />}
                  </td>
                  <td className="px-3 py-2 text-right" data-numeric>{formatNumber(String(mk.observation_count))}</td>
                  <td className="px-3 py-2">
                    {mk.missing_fields.length === 0 ? (
                      <span className="text-ink-3">none missing</span>
                    ) : (
                      <span className="flex flex-wrap gap-1.5">
                        {mk.missing_fields.map((f) => (
                          <Badge key={f} tone="warn">{humanize(f)}</Badge>
                        ))}
                      </span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Sub title="Current state" />
      <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <dt className="text-label uppercase text-ink-3">Lifecycle state</dt>
          <dd>{audit.lifecycle_state ? humanize(audit.lifecycle_state) : <Unavailable reason="not_classified" />}</dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Divergence case</dt>
          <dd>{audit.divergence_case ? humanize(audit.divergence_case) : <Unavailable reason="not_classified" />}</dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Mentions (1h)</dt>
          <dd><MeasuredValue measured={audit.attention.mentions_1h} format={formatNumber} /></dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Attention velocity</dt>
          <dd><MeasuredValue measured={audit.attention.velocity} format={formatNumber} /></dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Attention acceleration</dt>
          <dd><MeasuredValue measured={audit.attention.acceleration} format={formatNumber} /></dd>
        </div>
        <div>
          <dt className="text-label uppercase text-ink-3">Baseline multiple</dt>
          <dd><MeasuredValue measured={audit.attention.baseline_multiple} format={formatMultiple} /></dd>
        </div>
      </dl>

      <Sub title="Collection priority" />
      <div data-testid="collection-priority" className="flex flex-col gap-1 text-sm">
        <span className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">{humanize(priority.level)}</Badge>
          <span data-numeric>{formatInterval(priority.interval_seconds)}</span>
        </span>
        <span className="text-ink-2">{humanize(priority.reason)}</span>
        <span className="text-xs text-ink-3">
          Collection frequency only; not used in trading decisions.
        </span>
      </div>
    </Panel>
  );
}

export function AuditTrail({ slug }: { slug: string }) {
  const { data, isLoading, isError, refetch } = useLifecycleMemeQuality(slug);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !data) {
    return (
      <Panel>
        <ErrorState
          title="Could not load the audit trail"
          body="The meme quality endpoint did not answer."
          onRetry={() => void refetch()}
        />
      </Panel>
    );
  }
  return <AuditTrailView audit={data} />;
}

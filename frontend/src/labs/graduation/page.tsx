"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { shortenAddress } from "@/lib/format";

import { useGraduationStatus } from "./hooks";
import type { Funnel, RecentToken } from "./types";

/**
 * GRADUATION LAB
 *
 * pump.fun tokens on their way up the bonding curve, and what happens in the
 * hour after they graduate. A STATUS BOARD, not a strategy: it reports what
 * the recorder has seen and ranks nothing.
 *
 * Every figure is computed on the backend. Nothing here applies a threshold —
 * a rule written in the page would be a second, unpublished rule competing
 * with the one the recorder followed.
 */

const STAGES: { key: keyof Funnel; label: string; note: string }[] = [
  { key: "seen", label: "Seen", note: "admitted from the launch feed" },
  { key: "crossed_70", label: "70%", note: "tracked from here" },
  { key: "crossed_80", label: "80%", note: "" },
  { key: "crossed_90", label: "90%", note: "" },
  { key: "crossed_95", label: "95%", note: "" },
  { key: "graduated", label: "Graduated", note: "curve filled" },
];

function pct(part: number, whole: number): string {
  if (!whole) return "—";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

function progress(value: string | null): string {
  if (value === null) return "—";
  return `${Number(value).toFixed(1)}%`;
}

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-ink-dim">
        {label}
      </span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      {note ? <span className="text-xs text-ink-dim">{note}</span> : null}
    </div>
  );
}

function TokenRow({ token }: { token: RecentToken }) {
  return (
    <tr className="border-t border-line">
      <td className="py-2 pr-3 font-medium">
        {token.symbol ?? <span className="text-ink-dim">unnamed</span>}
      </td>
      <td className="py-2 pr-3 font-mono text-xs text-ink-dim">
        {shortenAddress(token.mint)}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums">
        {progress(token.max_progress_pct)}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-ink-dim">
        {token.sample_count}
      </td>
      <td className="py-2 text-right">
        {token.migrated ? (
          <span className="rounded-full bg-up/15 px-2 py-0.5 text-[11px] text-up">
            graduated
          </span>
        ) : token.tracked ? (
          <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] text-accent">
            tracking
          </span>
        ) : (
          <span className="text-[11px] text-ink-dim">watching</span>
        )}
      </td>
    </tr>
  );
}

export function GraduationLabPage() {
  const { data, isLoading, isError, refetch } = useGraduationStatus();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="p-6">
        <ErrorState
          title="Could not load the Graduation Lab"
          body="The status endpoint did not answer."
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (!data.running) {
    return (
      <div className="p-6">
        <EmptyState
          title="The Graduation Lab is not running"
          body="LAB_GRADUATION_ENABLED is off, so the recorder is not connected. This is not the same as the lab running and finding nothing — no tokens are being watched at all."
        />
      </div>
    );
  }

  const { funnel, signals } = data;

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">Graduation Lab</h1>
        <p className="max-w-[65ch] text-sm text-ink-dim">
          pump.fun tokens climbing the bonding curve, recorded from the free
          launch feed and a {data.poll_interval_s}s chain poll. Watching only —
          there is no book and nothing is ranked.
        </p>
      </header>

      <Panel>
        <PanelHeader>
          <PanelTitle>Right now</PanelTitle>
        </PanelHeader>
        <div className="grid grid-cols-2 gap-6 p-4 sm:grid-cols-4">
          <Stat
            label="Watch set"
            value={`${data.watch_set}`}
            note={`of ${data.watch_set_max} max`}
          />
          <Stat
            label="RPC calls / min"
            value={`${data.rpc_calls_per_minute}`}
            note="derived from the watch set"
          />
          <Stat
            label="New tokens / hr"
            value={`${data.tokens_last_hour}`}
            note="admitted from the feed"
          />
          <Stat
            label="Curve samples / hr"
            value={`${data.samples_last_hour}`}
            note="written only when reserves move"
          />
        </div>
      </Panel>

      <Panel>
        <PanelHeader>
          <PanelTitle>How far they get</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto p-4">
          <div className="flex min-w-[520px] items-end gap-2">
            {STAGES.map((stage) => {
              const value = funnel[stage.key];
              const share = funnel.seen ? value / funnel.seen : 0;
              return (
                <div key={stage.key} className="flex flex-1 flex-col gap-2">
                  <div className="flex h-28 items-end">
                    <div
                      className="w-full rounded-t bg-accent/70"
                      style={{ height: `${Math.max(share * 100, 1.5)}%` }}
                    />
                  </div>
                  <div className="flex flex-col gap-0.5 border-t border-line pt-2">
                    <span className="text-sm font-semibold tabular-nums">
                      {value}
                    </span>
                    <span className="text-[11px] uppercase tracking-wider text-ink-dim">
                      {stage.label}
                    </span>
                    <span className="text-[11px] tabular-nums text-ink-dim">
                      {pct(value, funnel.seen)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHeader>
            <PanelTitle>Graduation signals</PanelTitle>
          </PanelHeader>
          <div className="flex flex-col gap-3 p-4">
            <p className="max-w-[60ch] text-xs text-ink-dim">
              Two independent sources report a graduation — the migration feed
              and the curve account&rsquo;s own <code>complete</code> flag —
              and either can arrive alone. Counting one would undercount.
            </p>
            <dl className="flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-dim">Both agreed</dt>
                <dd className="tabular-nums">{signals.both}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Feed only</dt>
                <dd className="tabular-nums">{signals.feed_only}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Chain only</dt>
                <dd className="tabular-nums">{signals.chain_only}</dd>
              </div>
            </dl>
          </div>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>What has been recorded</PanelTitle>
          </PanelHeader>
          <div className="flex flex-col gap-3 p-4">
            <dl className="flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-dim">Curve samples</dt>
                <dd className="tabular-nums">{data.curve_samples}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Checkpoints</dt>
                <dd className="tabular-nums">{data.checkpoints}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">…of those, with reserves</dt>
                <dd className="tabular-nums">
                  {data.checkpoints_with_reserves}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Post-graduation samples</dt>
                <dd className="tabular-nums">{data.postgrad_samples}</dd>
              </div>
            </dl>
            {!data.quote_side_trusted ? (
              <p className="max-w-[60ch] rounded border border-warn/40 bg-warn/10 p-3 text-xs text-warn">
                The curve&rsquo;s quote side is under review: reserve and market-cap
                figures move inconsistently against the token side on live data
                and should not be relied on. Progress and the checkpoints are
                unaffected.
              </p>
            ) : null}
          </div>
        </Panel>
      </div>

      <Panel>
        <PanelHeader>
          <PanelTitle>Furthest up the curve</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto p-4">
          {data.recent.length === 0 ? (
            <EmptyState
              title="Nothing has moved yet"
              body="No watched token has recorded a progress reading."
            />
          ) : (
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-ink-dim">
                  <th className="pb-2 pr-3 font-medium">Symbol</th>
                  <th className="pb-2 pr-3 font-medium">Mint</th>
                  <th className="pb-2 pr-3 text-right font-medium">Peak</th>
                  <th className="pb-2 pr-3 text-right font-medium">Samples</th>
                  <th className="pb-2 text-right font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((token) => (
                  <TokenRow key={token.mint} token={token} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Panel>

      <p className="text-xs text-ink-dim">
        Polling {data.rpc_host} · recorder refreshes every{" "}
        {data.poll_interval_s}s · this page every 30s
      </p>
    </div>
  );
}

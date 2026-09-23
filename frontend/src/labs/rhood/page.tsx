"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import { useRhoodStatus } from "./hooks";
import type { RhoodEvent } from "./types";

/**
 * ROBINHOOD CHAIN — A RECORDER, NOT A LAB.
 *
 * There is no strategy here: no arms, no book, no wallet, and nothing on this
 * page has ever placed an order. It watches the pool factory on chain 4663 and
 * writes down what it sees, because the graduation lab's numbers — a $500k
 * floor, a five-minute hold — were measured on pump.fun, and porting them to a
 * different chain would be assuming the answer rather than measuring it.
 *
 * TWO THINGS ARE GIVEN THE SAME PROMINENCE AS THE COUNTS, because a reader who
 * misses either will misread the page:
 *
 *  - LAUNCHES vs EVENTS. The factory fires both for a coin meeting the market
 *    for the first time and for an extra pool on one that already trades. The
 *    first version of this recorder watched a contract that only did the
 *    latter, and recorded the same two tokens for four minutes before that
 *    showed up. The split is the headline for that reason.
 *  - NOT PRICED YET. A pool the price feed has not indexed cannot be an entry
 *    price. How long that takes decides whether a strategy here is possible at
 *    all, so it is a figure and not a footnote.
 */

function when(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-ink/[0.02] p-3">
      <div className="text-[11px] uppercase tracking-wider text-ink-dim">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {hint ? <div className="mt-1 text-[12px] text-ink-dim">{hint}</div> : null}
    </div>
  );
}

function Row({ event }: { event: RhoodEvent }) {
  return (
    <tr className="border-t border-line/60">
      <td className="py-1.5 pr-3">{when(event.at)}</td>
      <td className="py-1.5 pr-3 font-medium">{event.symbol || "—"}</td>
      <td className="py-1.5 pr-3 text-ink-dim">{event.name || "—"}</td>
      <td className="py-1.5 pr-3 text-right tabular-nums">{event.pairs_seen ?? "—"}</td>
      <td className="py-1.5 pr-3">
        {event.is_launch ? (
          <span className="text-up">launch</span>
        ) : (
          <span className="text-ink-dim">extra pool</span>
        )}
      </td>
      <td className="py-1.5">
        {event.priced ? (
          <span className="text-ink-dim">priced</span>
        ) : (
          <span className="text-down">not indexed yet</span>
        )}
      </td>
    </tr>
  );
}

export function RhoodLabPage() {
  const { data, isLoading, isError, refetch } = useRhoodStatus();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !data) {
    return (
      <ErrorState
        title="Could not load the Robinhood Chain recorder"
        body="The recorder writes to its own tables and nothing else reads them, so this failing means the page could not reach the API — not that collection has stopped."
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Robinhood Chain</h1>
        <p className="mt-1 max-w-[78ch] text-[13px] leading-relaxed text-ink-dim">
          A <b>recorder</b>, not a lab. It watches the pool factory on chain{" "}
          {data.chain_id} and writes down every token that meets the market, so
          that any strategy here can later be tested against a real record.{" "}
          <b>It has no arms, no book and no wallet</b>, and nothing here has ever
          placed an order. The graduation lab&apos;s thresholds were measured on
          pump.fun; assuming they transfer to a different chain is the mistake
          this is built to avoid.
        </p>
      </div>

      {!data.enabled ? (
        <EmptyState
          title="The recorder is switched off"
          body="LAB_RHOOD_ENABLED is not set, so nothing is being collected. This is not the same as the recorder running and finding nothing."
        />
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Figure
          label="Launches, 24h"
          value={String(data.launches_24h)}
          hint="first pool for a coin"
        />
        <Figure
          label="Launches, last hour"
          value={String(data.launches_1h)}
        />
        <Figure
          label="All factory events, 24h"
          value={String(data.events_24h)}
          hint="launches plus extra pools on coins that already trade"
        />
        <Figure
          label="Not indexed yet, 24h"
          value={String(data.unpriced_24h)}
          hint="no price available when the pool was made"
        />
      </div>

      <Panel>
        <PanelHeader>
          <PanelTitle>
            What it has seen{" "}
            <span className="font-normal text-ink-dim">
              &middot; {data.events_total} events, {data.samples} price readings
              {data.watching_since
                ? ` · since ${new Date(data.watching_since).toLocaleString()}`
                : ""}
            </span>
          </PanelTitle>
        </PanelHeader>
        {data.recent.length === 0 ? (
          <EmptyState
            title="Nothing recorded yet"
            body="The factory makes about six pools an hour, so the first rows can take a few minutes."
          />
        ) : (
          <div className="overflow-x-auto p-3">
            <table className="w-full text-[13px]">
              <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
                <tr>
                  <th className="py-1 pr-3 text-left font-normal">time</th>
                  <th className="py-1 pr-3 text-left font-normal">symbol</th>
                  <th className="py-1 pr-3 text-left font-normal">name</th>
                  <th className="py-1 pr-3 text-right font-normal">pairs</th>
                  <th className="py-1 pr-3 text-left font-normal">what it is</th>
                  <th className="py-1 text-left font-normal">price feed</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((event) => (
                  <Row key={`${event.token}-${event.at}`} event={event} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="max-w-[78ch] text-[12px] leading-relaxed text-ink-dim">
        Factory <code>{data.factory}</code>. A token&apos;s pool is pinned by the
        chain — the creation event carries the pool it made, so no pair is ever
        chosen here. That matters: one token on this chain has seven pairs from
        $1,146 to $157,675 of liquidity, and picking between them per reading is
        how an unpinned book once fabricated $2,414 of profit while looking like
        a price move.
      </p>
    </div>
  );
}

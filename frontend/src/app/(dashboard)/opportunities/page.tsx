"use client";

import { useMemo, useState } from "react";

import { BoardFilterBar } from "@/components/opportunity/board-filters";
import { OpportunityCard } from "@/components/opportunity/opportunity-card";
import { OpportunityDrawer } from "@/components/opportunity/opportunity-drawer";
import { StatusDot } from "@/components/ui/badge";
import { Label, Panel } from "@/components/ui/panel";
import { SkeletonTokenCard } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useOpportunities } from "@/hooks/use-opportunities";
import {
  NO_FILTERS,
  applyFilters,
  hasActiveFilters,
  signalTypesIn,
  sortOpportunities,
  type BoardFilters,
  type SortKey,
} from "@/lib/opportunities";
import type { Opportunity } from "@/types/opportunity";

/**
 * THE LIVE OPPORTUNITY BOARD
 *
 * The Radar answers "which projects are getting stronger?". This answers
 * "what became interesting *just now*?" — a different question, which is why it
 * is a different screen rather than a tab on the Radar.
 *
 * Every card exists because something changed. The token may be weeks old; the
 * signal is new, and it expires. A board that filled up over time would be a
 * leaderboard, and the platform already has one of those.
 *
 * **An empty board is a truthful board.** It means nothing changed. It is never
 * to be "fixed" by relaxing what qualifies — `/system` is where a reader
 * distinguishes a quiet market from a stalled pipeline.
 */
export default function OpportunitiesPage() {
  const [filters, setFilters] = useState<BoardFilters>(NO_FILTERS);
  const [sort, setSort] = useState<SortKey>("priority");
  const [selected, setSelected] = useState<Opportunity | null>(null);

  const { data, isPending, isError, refetch, isFetching } = useOpportunities();

  const items = useMemo(() => data?.items ?? [], [data]);
  const availableSignals = useMemo(() => signalTypesIn(items), [items]);
  const visible = useMemo(
    () => sortOpportunities(applyFilters(items, filters), sort),
    [items, filters, sort],
  );

  // The drawer reads from the freshly polled list rather than from the snapshot
  // captured at click time, so an open drawer stays current across a refetch.
  const open = selected
    ? (items.find((item) => item.mint_address === selected.mint_address) ?? selected)
    : null;

  const engineOff = data?.applied_filters.engine_enabled === false;
  const filtered = hasActiveFilters(filters);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Opportunity Engine</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            What became interesting now
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-dim">
            Every card below exists because something changed. The token may be days or
            weeks old — the signal is new, and it expires. Nothing here ranks by size.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-faint">
          <StatusDot live={isFetching} tone="var(--color-plasma)" />
          <span>{isFetching ? "Refreshing" : "Live · every 60s"}</span>
        </div>
      </header>

      <BoardFilterBar
        filters={filters}
        onChange={setFilters}
        sort={sort}
        onSortChange={setSort}
        availableSignals={availableSignals}
      />

      {isError ? (
        <ErrorState
          body="The Opportunity Engine is not responding. Detections already recorded are safe — this view will recover on its own."
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <SkeletonTokenCard key={index} />
          ))}
        </div>
      ) : engineOff ? (
        <Panel density="compact" className="border-warn/20 bg-warn/[0.03]">
          <Label>Engine not running</Label>
          <p className="mt-2 text-sm leading-relaxed text-ink-dim">
            The Opportunity Engine is not switched on in this environment, so nothing is
            being detected. This is a configuration state, not a fault — the board will
            fill once detection is enabled.
          </p>
        </Panel>
      ) : visible.length === 0 ? (
        <EmptyState
          agent={filtered ? "oracle" : "scout"}
          title={filtered ? "Nothing matches this view" : "Nothing is happening right now"}
          body={
            filtered
              ? "No live opportunity matches these filters. Widen them, or clear the search."
              : "An empty board means nothing changed — not that the platform is idle. Signals expire on purpose, so this fills and empties through the day."
          }
          action={
            filtered ? (
              <button
                type="button"
                onClick={() => setFilters(NO_FILTERS)}
                className="rounded-chip border border-line px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-line-bright hover:text-ink"
              >
                Clear filters
              </button>
            ) : undefined
          }
        />
      ) : (
        <>
          <p className="text-xs text-ink-faint">
            {visible.length}{" "}
            {visible.length === 1 ? "live opportunity" : "live opportunities"}
            {filtered && items.length !== visible.length && ` of ${items.length}`}
            {data.has_more && " · more available"}
          </p>
          <div className="grid items-start gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {visible.map((opportunity) => (
              <OpportunityCard
                key={`${opportunity.mint_address}:${opportunity.generation}`}
                opportunity={opportunity}
                onOpen={setSelected}
              />
            ))}
          </div>
        </>
      )}

      <OpportunityDrawer opportunity={open} onClose={() => setSelected(null)} />
    </div>
  );
}

"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { PaperWalletWidget } from "@/components/paper/wallet-widget";
import { FreshDetectedTokens } from "@/components/radar/fresh-detected-tokens";
import { QuickDetail } from "@/components/scanner/quick-detail";
import { ScannerTable } from "@/components/scanner/scanner-table";
import { ScannerToolbar } from "@/components/scanner/scanner-toolbar";
import { SegmentedControl } from "@/components/ui/filters";
import { LiveStatus } from "@/components/ui/freshness";
import { Panel } from "@/components/ui/panel";
import { useTableSort, type SortState } from "@/components/ui/data-table";
import { ErrorState } from "@/components/ui/states";
import { Toolbar } from "@/components/ui/toolbar";
import { InfoTip } from "@/components/ui/tooltip";
import { usePaperPositions } from "@/hooks/use-paper";
import { useRadar } from "@/hooks/use-radar";
import { byMint, paperStateFor } from "@/lib/paper";
import { rankDeltas } from "@/lib/motion";
import {
  DEFAULT_FILTERS,
  matchesFilters,
  scannerSortValue,
  withRank,
  type RankedEntry,
  type ScannerFilters,
  type ServerSort,
} from "@/lib/scanner";

/**
 * THE SCANNER — the primary decision surface.
 *
 * It answers one question: *which token deserves attention right now, why, and
 * what is the risk?* Everything on the page is arranged around answering that
 * without opening anything.
 *
 * TWO LAYERS OF ORDERING, AND THE DIFFERENCE MATTERS
 *
 * `Ranking` re-queries the server. `/radar` sorts by `score | detected | peak |
 * current`, and changing it can change *which* opportunities are on the page.
 *
 * Clicking a column header sorts **only the rows already fetched**. That is a
 * genuinely different operation and the toolbar says so, because a client sort
 * silently presented as a global one is how a reader concludes they have seen
 * the highest-liquidity token when they have seen the highest-liquidity token
 * *of fifty*.
 *
 * Through both, the `#` column keeps showing the backend's rank. It is the
 * product's opinion, not a label for scroll position — renumbering it 1..n
 * under a client sort would turn a claim into a description of the sort the
 * reader just chose.
 *
 * PAGE SIZE — A DELIBERATE PRODUCT CHANGE
 *
 * The card list showed 10, a client-side constant. `/radar` accepts up to 100
 * and this now requests 50. That is a product decision, not a backend change:
 * a scanner exists to be scanned, and ten rows is a shortlist. The old page's
 * argument for ten — "a ranked list nobody can finish is a leaderboard wearing
 * a recommendation's clothes" — was an argument against *ten tall cards*, and
 * it is answered by density rather than by truncation. No backend limit moved.
 */

const PAGE_SIZE = 50;

const RANKING_OPTIONS: { value: ServerSort; label: string }[] = [
  { value: "score", label: "Score" },
  { value: "detected", label: "Newest" },
  { value: "peak", label: "Peak" },
  { value: "current", label: "Current" },
];

export default function ScannerPage() {
  const [ranking, setRanking] = useState<ServerSort>("score");
  const [filters, setFilters] = useState<ScannerFilters>(DEFAULT_FILTERS);
  const [inspecting, setInspecting] = useState<RankedEntry | null>(null);

  const { data, isPending, isError, refetch, isFetching } = useRadar({
    pageSize: PAGE_SIZE,
    sort: ranking,
  });

  const paper = usePaperPositions();
  const traded = useMemo(() => byMint(paper.data?.items ?? []), [paper.data]);
  const paperStateOf = useCallback(
    (mint: string) => paperStateFor(traded.get(mint)),
    [traded],
  );

  // The server's order, stamped on before anything client-side can move it.
  const ranked = useMemo(() => withRank(data?.items ?? []), [data]);

  // Which tokens changed place in the *backend* ranking since the last fetch.
  // Computed from the server order, so it stays meaningful under a client sort.
  const previousOrder = useRef<string[]>([]);
  const deltas = useMemo(() => {
    const order = ranked.map((entry) => entry.mint_address);
    const moved = rankDeltas(previousOrder.current, order);
    previousOrder.current = order;
    return moved;
  }, [ranked]);
  const rankDeltaOf = useCallback((mint: string) => deltas.get(mint) ?? 0, [deltas]);

  const filtered = useMemo(
    () => ranked.filter((entry) => matchesFilters(entry, filters)),
    [ranked, filters],
  );

  const { sort, setSort, sorted } = useTableSort<RankedEntry>(
    filtered,
    scannerSortValue,
    { key: "rank", direction: "asc" },
  );

  // Column sorting stays local, always.
  //
  // An earlier draft handed Score/Peak/Current off to the server because those
  // three happen to be server-sortable. It was worse: clicking a header
  // sometimes refetched and changed which rows were present and sometimes did
  // not, with nothing to tell the two apart. One control per behaviour —
  // headers reorder what you can see, Ranking re-queries — is predictable, and
  // it is what the toolbar tells the reader.
  const onSortChange = useCallback((next: SortState) => setSort(next), [setSort]);

  const timestamps = useMemo(
    () => ranked.map((entry) => entry.market?.captured_at),
    [ranked],
  );

  return (
    <div className="flex flex-col gap-4">
      <Toolbar
        eyebrow="Scanner"
        title="Live opportunities"
        actions={
          <>
            <LiveStatus timestamps={timestamps} pending={isPending} />
            <span aria-hidden className="h-4 w-px bg-line" />
            <SegmentedControl
              label="Ranking"
              options={RANKING_OPTIONS}
              value={ranking}
              onChange={(value) => {
                setRanking(value);
                setSort({ key: "rank", direction: "asc" });
              }}
            />
            <InfoTip
              label="ranking"
              content="Re-queries the Radar. Unlike sorting a column, this can change which opportunities appear."
            />
          </>
        }
        filters={
          <ScannerToolbar
            filters={filters}
            onChange={setFilters}
            shown={sorted.length}
            total={data?.total ?? ranked.length}
          />
        }
      />

      {isError ? (
        <ErrorState
          body="The Radar is not responding. Detections already recorded are safe — this view will recover on its own."
          onRetry={() => void refetch()}
        />
      ) : (
        <ScannerTable
          rows={sorted}
          sort={sort}
          onSortChange={onSortChange}
          onInspect={setInspecting}
          activeMint={inspecting?.mint_address ?? null}
          isPending={isPending}
          paperStateOf={paperStateOf}
          rankDeltaOf={rankDeltaOf}
          empty={
            ranked.length === 0 ? (
              // An empty Radar is a truthful Radar: nothing clears the model's
              // floor right now. It is never to be "fixed" by relaxing entry.
              //
              // The frog used to stand here. Inside the terminal the space
              // identity is carried by the universe behind the interface, not
              // by the mascot appearing in a data surface — the gate is where
              // the character lives.
              <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
                <p className="text-sm text-ink">Nothing clears the floor right now</p>
                <p className="max-w-sm text-xs leading-relaxed text-ink-3">
                  An empty Radar is a truthful Radar. Nothing currently meets the
                  model&rsquo;s minimum score, confidence and risk thresholds, and
                  admission is never relaxed to fill this space.
                </p>
                <Link
                  href="/record"
                  className="rounded-md border border-line-control px-3 py-1.5 text-xs text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
                >
                  Open the track record
                </Link>
              </div>
            ) : (
              <div className="px-3 py-10 text-center">
                <p className="text-sm text-ink-2">
                  No opportunity matches these filters.
                </p>
                <button
                  type="button"
                  onClick={() => setFilters(DEFAULT_FILTERS)}
                  className="mt-2 text-xs text-accent hover:underline"
                >
                  Clear filters
                </button>
              </div>
            )
          }
        />
      )}

      {/* Refresh is reported without moving anything: a table that reflowed on
          every poll would be unusable, and a spinner over loaded rows implies
          the figures under it are wrong when they are merely a moment old. */}
      <p className="h-4 text-xs text-ink-4" aria-live="polite">
        {isFetching && !isPending ? "Refreshing…" : ""}
      </p>

      <div className="grid gap-4 xl:grid-cols-2">
        <PaperWalletWidget />
        <FreshDetectedTokens />
      </div>

      <Panel density="compact">
        <p className="text-xs leading-relaxed text-ink-2">
          Base rates describe what happened to <em>past</em> detections in the same
          category. They are measured over the permanent record, losers included, and
          make no claim about any token above. Peak and current are always shown
          together — a call that reached 18× and fell to 0.30× is not an 18× call.
        </p>
        <Link
          href="/record"
          className="mt-2 inline-block text-xs text-ink-3 underline transition-colors hover:text-ink"
        >
          See every token we have ever detected
        </Link>
      </Panel>

      <QuickDetail entry={inspecting} onClose={() => setInspecting(null)} />
    </div>
  );
}

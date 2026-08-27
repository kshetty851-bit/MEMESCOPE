"use client";

import { useCallback, useMemo, useState } from "react";

import { TokenCell } from "@/components/scanner/token-cell";
import { DataTable, useTableSort, type Column } from "@/components/ui/data-table";
import { FilterBar, SegmentedControl } from "@/components/ui/filters";
import { FreshnessLabel, LiveStatus, NoMarketData } from "@/components/ui/freshness";
import { Num } from "@/components/ui/num";
import { Panel } from "@/components/ui/panel";
import { Stat, StatRow } from "@/components/ui/stat";
import { Toolbar } from "@/components/ui/toolbar";
import { InfoTip } from "@/components/ui/tooltip";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { HistoryFeed } from "@/components/record/history-feed";
import { Journey } from "@/components/record/journey";
import { usePaperPositions } from "@/hooks/use-paper";
import {
  byMint,
  clock,
  entryDelaySeconds,
  epoch,
  exitLabel,
  formatDelay,
  stamp,
  usd,
} from "@/lib/paper";
import { num } from "@/lib/design/bands";
import {
  useAllRadarDetections,
  useRadarBenchmark,
  useRadarPerformance,
} from "@/hooks/use-radar";
import { compactUsd } from "@/lib/radar-row";
import { formatMultiple } from "@/lib/radar";
import { cn } from "@/lib/utils";
import type { PaperPosition } from "@/types/paper";
import type { RadarEntry } from "@/types/radar";

/**
 * TRACK RECORD — the permanent record of every Radar detection, losers
 * included. This page is the argument for trusting anything else in the
 * product, and it only works if it is complete.
 *
 * Three rules are unchanged and still enforced rather than intended:
 *
 *  - **Nothing is hidden.** No filter removes losing outcomes, and the default
 *    order is newest-first, not best-first. Sorting by performance by default
 *    is a Hall of Fame wearing a track record's name.
 *  - **Peak and current always appear together.** A call that reached 18× and
 *    fell to 0.30× is not an 18× call.
 *  - **Nothing is estimated.** Every absent figure renders a dash, never zero.
 *
 * What changed in Phase 7 is presentation only. The tier badges were emoji —
 * ⭐ ⭐⭐ ⭐⭐⭐ 🏆 🚀 👑 — which render as full-colour illustrations that ignore
 * the palette, change shape per platform, and turn an evidence table into a
 * scoreboard. They are now a typographic chip carrying the same stored tiers.
 * The hand-rolled 17-column table became a `DataTable` with a sticky header,
 * so the column names survive past row twelve.
 */

const TIER_ORDER = ["2x", "5x", "10x", "25x", "50x", "100x", "250x", "500x", "1000x"];

type ReachedFilter = "all" | "2x" | "5x" | "10x";

function days(value: string | null | undefined): string | null {
  const parsed = num(value);
  return parsed === null ? null : `${parsed.toFixed(1)}d`;
}

function pct(value: string | null | undefined): string | null {
  const parsed = num(value);
  return parsed === null ? null : `${(parsed * 100).toFixed(0)}%`;
}

/**
 * The highest tier a detection ever reached, as type rather than as an emoji.
 *
 * Read from `achieved_tiers`, never from the current multiple: tiers are
 * permanent once earned, because a later fall cannot erase a high that
 * happened. No tier is a real and common state and renders as a dash.
 */
function BestTier({ tiers }: { tiers: string[] }) {
  if (tiers.length === 0) {
    return <Num value={null} absentLabel="no tier reached" />;
  }

  const best = [...tiers]
    .sort((a, b) => TIER_ORDER.indexOf(a) - TIER_ORDER.indexOf(b))
    .at(-1)!;
  const magnitude = Number(best.replace("x", "")) || 0;

  return (
    <span
      data-numeric
      className={cn(
        "inline-flex items-center rounded-sm border px-1.5 py-0.5 text-xs font-medium tabular-nums",
        // One scarce colour at the very top, ink everywhere else. A ladder of
        // six hues would make every row shout.
        magnitude >= 100
          ? "border-score-elite/40 bg-score-elite/10 text-score-elite"
          : magnitude >= 10
            ? "border-up/30 bg-up/10 text-up"
            : "border-line text-ink-2",
      )}
      title={`Tiers reached: ${tiers.join(", ")}`}
    >
      {best.replace("x", "×")}
    </span>
  );
}

/**
 * Was this token traded, and how did it go?
 *
 * Deliberately never offers an action. The strategy enters on its own published
 * rule with no manual step, so a token the wallet has not taken reads "—",
 * never "buy".
 */
function PaperCell({ position }: { position: PaperPosition | undefined }) {
  if (!position) return <Num value={null} absentLabel="not traded" />;

  const closed = position.status === "closed";

  return (
    <span
      className="whitespace-nowrap"
      title={
        closed
          ? `${exitLabel(position.exit_reason) ?? "Closed"} · entered at rank #${position.entry_rank}`
          : `Open · entered at rank #${position.entry_rank}`
      }
    >
      <Num
        value={position.pnl_usd}
        display={usd(position.pnl_usd)}
        signed
        className="text-sm"
      />
      <span className="ml-1.5 text-xs text-ink-3">
        {closed ? (exitLabel(position.exit_reason) ?? "closed") : "open"}
      </span>
    </span>
  );
}

export default function TrackRecordPage() {
  const performance = useRadarPerformance();
  const benchmark = useRadarBenchmark();
  // The whole record, not a page of it: this table's entire purpose is that
  // nothing is left out, and `includeInactive` keeps dead entries in.
  const record = useAllRadarDetections({ includeInactive: true, sort: "detected" });
  const paper = usePaperPositions();

  const [reached, setReached] = useState<ReachedFilter>("all");

  const traded = useMemo(() => byMint(paper.data?.items ?? []), [paper.data]);

  const rows = useMemo(() => {
    const items: RadarEntry[] = record.data?.items ?? [];
    if (reached === "all") return items;
    const threshold = Number(reached.replace("x", ""));
    return items.filter((item) => (num(item.peak_multiple) ?? 0) >= threshold);
  }, [record.data, reached]);

  const selectValue = useCallback(
    (row: RadarEntry, key: string) => {
      switch (key) {
        case "detected":
          return num(row.first_market_cap);
        case "now":
          return num(row.current_market_cap);
        case "peakCap":
          return num(row.peak_market_cap);
        case "current":
          return num(row.current_multiple);
        case "peak":
          return num(row.peak_multiple);
        case "age":
          return num(row.days_since_detection);
        case "paper":
          return num(traded.get(row.mint_address)?.pnl_usd);
        case "detectedAt":
          return epoch(row.discovered_at);
        case "entryAt":
          return epoch(traded.get(row.mint_address)?.opened_at);
        case "entryDelay":
          return entryDelaySeconds(
            row.discovered_at,
            traded.get(row.mint_address)?.opened_at,
          );
        default:
          return null;
      }
    },
    [traded],
  );

  // `null` initial sort: the server already returned newest-first, and leaving
  // it unsorted preserves that without the table asserting an opinion.
  const { sort, setSort, sorted } = useTableSort<RadarEntry>(rows, selectValue, null);

  const columns = useMemo<Column<RadarEntry>[]>(
    () => [
      {
        key: "index",
        header: "#",
        align: "right",
        width: "44px",
        cell: (_row, index) => (
          <span data-numeric className="text-xs text-ink-3">
            {index + 1}
          </span>
        ),
      },
      {
        key: "token",
        header: "Token",
        pinned: true,
        width: "200px",
        cell: (row) => (
          <TokenCell
            mint={row.mint_address}
            name={row.name}
            symbol={row.symbol}
            imageUrl={row.image_url}
          />
        ),
      },
      {
        key: "detected",
        header: "Detected",
        align: "right",
        width: "84px",
        sortable: true,
        srHeader: "Market cap at detection",
        cell: (row) => (
          <Num
            value={row.first_market_cap}
            display={compactUsd(row.first_market_cap)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "now",
        header: "Now",
        align: "right",
        width: "96px",
        sortable: true,
        srHeader: "Current market cap",
        cell: (row) => (
          <span className="flex flex-col items-end">
            <Num
              value={row.current_market_cap}
              display={compactUsd(row.current_market_cap)}
              className="text-sm"
            />
            {/* "Now" is live and carries its reading's age. Detected and Peak
                are historical: a recorded past cannot go stale. */}
            {row.market?.captured_at ? (
              <FreshnessLabel
                capturedAt={row.market.captured_at}
                className="text-[0.625rem]"
              />
            ) : (
              <NoMarketData className="text-[0.625rem]" />
            )}
          </span>
        ),
      },
      {
        key: "peakCap",
        header: "Peak",
        align: "right",
        width: "84px",
        sortable: true,
        srHeader: "Peak market cap",
        headerClassName: "hidden xl:table-cell",
        cellClassName: "hidden xl:table-cell",
        cell: (row) => (
          <Num
            value={row.peak_market_cap}
            display={compactUsd(row.peak_market_cap)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "current",
        header: "Now ×",
        align: "right",
        width: "72px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.current_multiple}
            display={formatMultiple(row.current_multiple)}
            signed
            pivot={1}
            className="text-sm"
          />
        ),
      },
      {
        // Immediately beside Now ×, always.
        key: "peak",
        header: "Peak ×",
        align: "right",
        width: "72px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.peak_multiple}
            display={formatMultiple(row.peak_multiple)}
            tone="muted"
            className="text-sm"
          />
        ),
      },
      {
        key: "tier",
        header: "Best tier",
        align: "center",
        width: "84px",
        cell: (row) => <BestTier tiers={row.achieved_tiers ?? []} />,
      },
      {
        key: "journey",
        header: "Journey",
        width: "230px",
        headerClassName: "hidden 2xl:table-cell",
        cellClassName: "hidden 2xl:table-cell",
        cell: (row) => (
          <Journey
            tiers={row.achieved_tiers ?? []}
            peakMultiple={row.peak_multiple}
            currentMultiple={row.current_multiple}
          />
        ),
      },
      {
        key: "age",
        header: "Tracked",
        align: "right",
        width: "76px",
        sortable: true,
        headerClassName: "hidden lg:table-cell",
        cellClassName: "hidden lg:table-cell",
        cell: (row) => (
          <Num
            value={row.days_since_detection}
            display={days(row.days_since_detection)}
            tone="muted"
            className="text-xs"
          />
        ),
      },
      {
        key: "status",
        header: "Status",
        width: "80px",
        headerClassName: "hidden lg:table-cell",
        cellClassName: "hidden lg:table-cell",
        cell: (row) => (
          <span
            className={cn(
              "text-xs",
              row.liveness === "alive" ? "text-ink-2" : "text-ink-3",
            )}
            title={
              row.liveness === "alive"
                ? "A market was observed in the last 24 hours"
                : "No market observed recently — this is not a claim that it died"
            }
          >
            {row.liveness === "alive" ? "Alive" : "Unknown"}
          </span>
        ),
      },
      {
        key: "paper",
        header: "Paper",
        align: "right",
        width: "120px",
        sortable: true,
        srHeader: "Paper wallet outcome",
        headerClassName: "hidden xl:table-cell",
        cellClassName: "hidden xl:table-cell",
        cell: (row) => <PaperCell position={traded.get(row.mint_address)} />,
      },
      {
        // DETECTION → ENTRY → EXIT. Placed after Paper because the last two are
        // trade facts, and deliberately far from the "Detected" column above,
        // which is a market cap in dollars rather than a clock.
        key: "detectedAt",
        header: "Detected at",
        align: "right",
        width: "92px",
        sortable: true,
        srHeader: "Detection time",
        cell: (row) => (
          <Num
            display={clock(row.discovered_at)}
            absentLabel="Not available"
            tone="flat"
            className="text-xs"
            title={
              stamp(row.discovered_at) ??
              "No discovery record is stored for this mint — the detection time is not available, and is not estimated."
            }
          />
        ),
      },
      {
        key: "entryAt",
        header: "Entry",
        align: "right",
        width: "96px",
        sortable: true,
        srHeader: "Paper wallet entry and exit time",
        headerClassName: "hidden lg:table-cell",
        cellClassName: "hidden lg:table-cell",
        cell: (row) => {
          const position = traded.get(row.mint_address);
          if (!position) return <Num value={null} absentLabel="not traded" />;
          const exit = position.closed_at;
          return (
            <span className="flex flex-col items-end leading-tight">
              <Num
                display={clock(position.opened_at)}
                absentLabel="Not available"
                className="text-xs"
                title={stamp(position.opened_at) ?? undefined}
              />
              <span
                className="text-[0.625rem] text-ink-3"
                title={exit ? (stamp(exit) ?? undefined) : "Still open"}
              >
                {exit ? `exit ${clock(exit)}` : "open"}
              </span>
            </span>
          );
        },
      },
      {
        key: "entryDelay",
        header: "Entry delay",
        align: "right",
        width: "88px",
        sortable: true,
        srHeader: "Time between detection and entry",
        headerClassName: "hidden lg:table-cell",
        cellClassName: "hidden lg:table-cell",
        cell: (row) => {
          const position = traded.get(row.mint_address);
          if (!position) return <Num value={null} absentLabel="not traded" />;
          const seconds = entryDelaySeconds(row.discovered_at, position.opened_at);
          return (
            <Num
              display={formatDelay(seconds)}
              absentLabel="Not available"
              tone="muted"
              className="text-xs"
              title={
                seconds === null
                  ? "No stored detection time for this mint, so the delay cannot be measured."
                  : `Detected ${clock(row.discovered_at)} · Entry ${clock(position.opened_at)} · ${formatDelay(seconds)}`
              }
            />
          );
        },
      },
    ],
    [traded],
  );

  if (performance.isError || record.isError) {
    return (
      <ErrorState
        body="The track record is not responding. The record itself is append-only and intact — this is a read failure."
        onRetry={() => void record.refetch()}
      />
    );
  }

  const data = performance.data;
  const total = data?.total_opportunities ?? 0;
  const tierCount = (tier: string) =>
    data?.tiers.find((entry) => entry.tier === tier)?.count ?? 0;

  return (
    <div className="flex flex-col gap-5 pb-8">
      <Toolbar
        eyebrow="Track record"
        title="Every detection. Every outcome. Nothing hidden."
        description="Measured from the moment each project was detected — never from launch. Losses are counted in the same denominator as wins, and nothing is removed once recorded."
        actions={
          <LiveStatus
            timestamps={(record.data?.items ?? []).map((item) => item.market?.captured_at)}
            pending={record.isPending}
          />
        }
      />

      {total === 0 && !performance.isPending ? (
        <EmptyState
          title="No detections recorded yet"
          body="The Radar has not detected anything yet. Once it does, every detection appears here permanently — including the ones that do not work out."
        />
      ) : (
        <>
          <StatRow className="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Total detected" value={total} size="lg" />
            <Stat
              label="Reached 2×"
              value={tierCount("2x")}
              display={
                total > 0
                  ? `${tierCount("2x")} · ${((tierCount("2x") / total) * 100).toFixed(0)}%`
                  : null
              }
              size="lg"
            />
            <Stat label="Reached 10×" value={tierCount("10x")} size="lg" />
            <Stat
              label="Median peak"
              value={data?.median_peak_multiple}
              display={formatMultiple(data?.median_peak_multiple)}
              size="lg"
            />
            <Stat
              label="Median now"
              value={data?.median_current_multiple}
              display={formatMultiple(data?.median_current_multiple)}
              signed
              pivot={1}
              size="lg"
            />
            <Stat
              label="Avg drawdown"
              value={data?.average_drawdown}
              display={pct(data?.average_drawdown)}
              tone="down"
              size="lg"
              hint="From peak"
            />
          </StatRow>

          <section className="flex flex-col gap-2.5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="flex items-center gap-1.5 text-sm font-medium text-ink">
                Every detection{" "}
                <span data-numeric className="font-normal text-ink-3">
                  ({sorted.length})
                </span>
                <InfoTip
                  label="this table"
                  content="Every Radar detection ever recorded, inactive ones included. There is no filter that removes losing outcomes, and the default order is newest first."
                />
              </h2>

              <FilterBar>
                <SegmentedControl
                  label="Reached at least"
                  options={[
                    { value: "all", label: "All" },
                    { value: "2x", label: "2×" },
                    { value: "5x", label: "5×" },
                    { value: "10x", label: "10×" },
                  ]}
                  value={reached}
                  onChange={(value) => setReached(value as ReachedFilter)}
                />
              </FilterBar>
            </div>

            <DataTable
              columns={columns}
              rows={sorted}
              getRowId={(row) => row.mint_address}
              caption="Every Radar detection and its outcome, newest first"
              sort={sort}
              onSortChange={setSort}
              density="compact"
              stickyHeader
              maxHeight="calc(100dvh - 24rem)"
              minWidth="980px"
              isPending={record.isPending}
              pendingRows={12}
              empty={
                <p className="px-3 py-10 text-center text-sm text-ink-3">
                  No detection reached that tier yet.
                </p>
              }
            />

            <p className="text-xs text-ink-3">
              Peak and current are always shown together. A call that reached 18×
              and gave it back is not an 18× call.
            </p>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <Panel density="comfortable" className="flex flex-col gap-3">
              <div>
                <h2 className="text-sm font-medium text-ink">Benchmark</h2>
                <p className="mt-1 text-xs leading-relaxed text-ink-3">
                  What buying every detection in equal size would have returned.
                  Measured from the record, not simulated.
                </p>
              </div>
              {benchmark.data ? (
                <>
                  <StatRow className="grid-cols-2">
                    <Stat
                      label="Buy every detection"
                      value={benchmark.data.average_current_multiple}
                      display={formatMultiple(benchmark.data.average_current_multiple)}
                      signed
                      pivot={1}
                      hint="Mean current multiple"
                    />
                    <Stat
                      label="Median outcome"
                      value={benchmark.data.median_current_multiple}
                      display={formatMultiple(benchmark.data.median_current_multiple)}
                      signed
                      pivot={1}
                      hint="The typical call"
                    />
                    <Stat
                      label="Above entry"
                      value={benchmark.data.above_entry}
                      display={`${benchmark.data.above_entry} of ${benchmark.data.entries}`}
                    />
                    <Stat
                      label="Below entry"
                      value={benchmark.data.below_entry}
                      display={`${benchmark.data.below_entry} of ${benchmark.data.entries}`}
                      tone="down"
                    />
                  </StatRow>
                  <div className="flex flex-col gap-1 text-xs leading-relaxed text-ink-3">
                    <p>Hold SOL — {benchmark.data.sol_note}</p>
                    <p>Paper wallet — {benchmark.data.paper_wallet_note}</p>
                  </div>
                </>
              ) : (
                <p className="text-xs text-ink-3">Loading benchmark…</p>
              )}
            </Panel>

            <Panel density="comfortable" className="flex flex-col gap-3">
              <div>
                <h2 className="text-sm font-medium text-ink">History</h2>
                <p className="mt-1 text-xs leading-relaxed text-ink-3">
                  Every detection and every milestone, newest first. Each line is
                  a stored row — nothing is written for this feed.
                </p>
              </div>
              <HistoryFeed />
            </Panel>
          </section>
        </>
      )}
    </div>
  );
}

"use client";

import { useMemo } from "react";

import { EvidenceDots, RadarScore } from "@/components/scanner/radar-score";
import { RowActions } from "@/components/scanner/row-actions";
import { TokenCell } from "@/components/scanner/token-cell";
import { DataTable, type Column, type SortState } from "@/components/ui/data-table";
import { Delta } from "@/components/ui/delta";
import { Num } from "@/components/ui/num";
import { RiskChip } from "@/components/ui/risk-chip";
import { Tooltip } from "@/components/ui/tooltip";
import { freshnessOf } from "@/lib/freshness";
import { formatMultiple } from "@/lib/radar";
import { compactAge, compactUsd, expiresIn } from "@/lib/radar-row";
import type { RankedEntry } from "@/lib/scanner";
import { useSharedClock } from "@/hooks/use-shared-clock";
import { cn } from "@/lib/utils";

/**
 * THE SCANNER TABLE.
 *
 * Columns were chosen from what `/radar` actually returns, not from a wishlist.
 * Two requested columns are deliberately absent, and both absences are real
 * findings rather than omissions:
 *
 *   - **Buy/sell activity.** `MarketStripOut` — the market object on the list
 *     response — carries price, market cap, liquidity, 24h volume, 24h change,
 *     captured_at and dex_name. No transaction counts. They exist only on the
 *     per-token snapshot, so they are in the quick-detail panel instead.
 *   - **Sparkline.** The list carries no price series. One per row would be one
 *     history request per row. The trace is in the quick-detail panel, where it
 *     costs a single request for the token actually being looked at.
 *
 * Fabricating either would have been trivial and wrong.
 *
 * Density: 32px rows at `compact`, driven by the 13px type scale rather than by
 * shrinking text. A 1440px screen shows roughly 22 rows against the old card
 * list's 4.
 */

/** Freshness as a dot, for a column that has to stay narrow. */
function FreshnessDot({ capturedAt }: { capturedAt: string | null | undefined }) {
  // One shared timer for every dot on the page — see `use-shared-clock`. The
  // subscription only schedules the re-render; the time is read at render.
  useSharedClock(30_000);
  const freshness = freshnessOf(capturedAt, Date.now());

  const tone = {
    fresh: "bg-up",
    normal: "bg-ink-3",
    ageing: "bg-warn",
    stale: "bg-down",
    unknown: "bg-line-strong",
  }[freshness.band];

  return (
    <Tooltip content={freshness.description} side="bottom">
      <span className="inline-flex items-center gap-1.5" tabIndex={0}>
        <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", tone)} />
        <span data-numeric className="text-xs text-ink-3">
          {freshness.ageSeconds === null
            ? "—"
            : (compactAge(freshness.ageSeconds) ?? "—")}
        </span>
        <span className="sr-only">{freshness.description}</span>
      </span>
    </Tooltip>
  );
}

/** Column visibility by width. Paired onto header and cell so they cannot drift. */
const AT_SM = "hidden sm:table-cell";
const AT_XL = "hidden xl:table-cell";
const AT_2XL = "hidden 2xl:table-cell";
/** Signal is the widest optional column and only earns its place on a big monitor. */
const AT_WIDE = "hidden min-[1700px]:table-cell";

export function ScannerTable({
  rows,
  sort,
  onSortChange,
  onInspect,
  activeMint,
  isPending,
  empty,
  paperStateOf,
  rankDeltaOf,
}: {
  rows: RankedEntry[];
  sort: SortState | null;
  onSortChange: (sort: SortState) => void;
  onInspect: (entry: RankedEntry) => void;
  activeMint: string | null;
  isPending: boolean;
  empty?: React.ReactNode;
  paperStateOf: (mint: string) => "not-held" | "open" | "closed";
  /** Places moved in the backend ranking since the last fetch. */
  rankDeltaOf: (mint: string) => number;
}) {
  const columns = useMemo<Column<RankedEntry>[]>(
    () => [
      {
        key: "rank",
        header: "#",
        align: "right",
        width: "40px",
        sortable: true,
        srHeader: "Radar rank",
        cell: (row) => {
          const delta = rankDeltaOf(row.mint_address);
          return (
            <span className="inline-flex items-baseline justify-end gap-0.5">
              <span data-numeric className="text-xs text-ink-3">
                {row.rank}
              </span>
              {/* Shown only while it is news. The marker disappears on the next
                  fetch that leaves the token in place, so a settled ranking
                  carries no marks at all. No animation — the appearance of the
                  glyph is itself the state change. */}
              {delta !== 0 ? (
                <>
                  <span
                    aria-hidden
                    className={cn(
                      "text-[0.5rem] leading-none",
                      delta > 0 ? "text-up" : "text-down",
                    )}
                  >
                    {delta > 0 ? "▲" : "▼"}
                  </span>
                  <span className="sr-only">
                    {delta > 0
                      ? `up ${delta} place${delta === 1 ? "" : "s"}`
                      : `down ${Math.abs(delta)} place${delta === -1 ? "" : "s"}`}
                  </span>
                </>
              ) : null}
            </span>
          );
        },
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
            paperState={paperStateOf(row.mint_address)}
          />
        ),
      },
      {
        key: "age",
        header: "Age",
        align: "right",
        width: "56px",
        sortable: true,
        headerClassName: AT_SM,
        cellClassName: AT_SM,
        cell: (row) => (
          <Num value={row.age_seconds} display={compactAge(row.age_seconds)} tone="muted" className="text-xs" />
        ),
      },
      {
        key: "price",
        header: "Price",
        align: "right",
        width: "80px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.market?.price_usd}
            display={compactUsd(row.market?.price_usd)}
            className="text-sm"
          />
        ),
      },
      {
        key: "marketCap",
        header: "Mkt cap",
        align: "right",
        width: "80px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.market?.market_cap}
            display={compactUsd(row.market?.market_cap)}
            className="text-sm"
          />
        ),
      },
      {
        key: "liquidity",
        header: "Liquidity",
        align: "right",
        width: "80px",
        sortable: true,
        headerClassName: AT_XL,
        cellClassName: AT_XL,
        cell: (row) => (
          <Num
            value={row.market?.liquidity_usd}
            display={compactUsd(row.market?.liquidity_usd)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "volume",
        header: "Vol 24h",
        align: "right",
        width: "80px",
        sortable: true,
        headerClassName: AT_XL,
        cellClassName: AT_XL,
        cell: (row) => (
          <Num
            value={row.market?.volume_24h}
            display={compactUsd(row.market?.volume_24h)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "change",
        header: "24h",
        align: "right",
        width: "72px",
        sortable: true,
        headerClassName: AT_XL,
        cellClassName: AT_XL,
        cell: (row) => <Delta value={row.market?.change_24h_pct} />,
      },
      {
        key: "current",
        header: "Now ×",
        align: "right",
        width: "64px",
        sortable: true,
        srHeader: "Current multiple since detection",
        headerClassName: AT_2XL,
        cellClassName: AT_2XL,
        cell: (row) => (
          <Num
            value={row.current_multiple}
            display={formatMultiple(row.current_multiple)}
            signed
            pivot={1}
            className="text-xs"
          />
        ),
      },
      {
        // Immediately beside Now ×, never on its own. A call that reached 18×
        // and gave it back is not an 18× call, and separating these would let a
        // reader see only the flattering half.
        key: "peak",
        header: "Peak ×",
        align: "right",
        width: "64px",
        sortable: true,
        srHeader: "Peak multiple since detection",
        headerClassName: AT_2XL,
        cellClassName: AT_2XL,
        cell: (row) => (
          <Num
            value={row.peak_multiple}
            display={formatMultiple(row.peak_multiple)}
            tone="muted"
            className="text-xs"
          />
        ),
      },
      {
        key: "score",
        header: "Score",
        align: "right",
        width: "100px",
        sortable: true,
        srHeader: "MEMESCOPE score",
        cell: (row) => (
          <RadarScore score={row.opportunity_score} category={row.category} />
        ),
      },
      {
        key: "evidence",
        header: "Evid.",
        align: "center",
        width: "48px",
        sortable: true,
        srHeader: "Evidence — share of the model that had data",
        headerClassName: AT_2XL,
        cellClassName: AT_2XL,
        cell: (row) => <EvidenceDots evidence={row.evidence} />,
      },
      {
        key: "risk",
        header: "Risk",
        width: "80px",
        sortable: true,
        cell: (row) => (
          <RiskChip band={row.risk_band} reasons={row.risk_reasons} variant="full" />
        ),
      },
      {
        key: "signal",
        header: "Signal",
        width: "110px",
        headerClassName: AT_WIDE,
        cellClassName: AT_WIDE,
        cell: (row) =>
          row.signal ? (
            <Tooltip
              content={`Expires in ${expiresIn(row.signal.expires_in_seconds) ?? "—"}`}
              side="bottom"
            >
              <span
                tabIndex={0}
                className="truncate rounded-sm border border-accent/25 bg-accent/[0.08] px-1.5 py-0.5 text-xs text-accent"
              >
                {row.signal.label}
              </span>
            </Tooltip>
          ) : (
            <span className="text-xs text-ink-4" aria-hidden>
              —
            </span>
          ),
      },
      {
        key: "data",
        header: "Data",
        width: "64px",
        srHeader: "How old the market reading is",
        cell: (row) => <FreshnessDot capturedAt={row.market?.captured_at} />,
      },
      {
        key: "actions",
        header: "",
        align: "right",
        width: "40px",
        srHeader: "Actions",
        cell: (row) => <RowActions mint={row.mint_address} symbol={row.symbol} />,
      },
    ],
    [paperStateOf, rankDeltaOf],
  );

  return (
    <DataTable
      columns={columns}
      rows={rows}
      getRowId={(row) => row.mint_address}
      caption="Radar opportunities, ranked by the MEMESCOPE score"
      sort={sort}
      onSortChange={onSortChange}
      density="compact"
      stickyHeader
      maxHeight="calc(100dvh - 15rem)"
      minWidth="700px"
      onRowClick={onInspect}
      isRowActive={(row) => row.mint_address === activeMint}
      isPending={isPending}
      pendingRows={12}
      empty={empty}
    />
  );
}

"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { DataTable, type Column } from "@/components/ui/data-table";
import { Delta } from "@/components/ui/delta";
import { Num } from "@/components/ui/num";
import { Sparkline } from "@/components/ui/sparkline";
import { api } from "@/lib/api-client";
import { buySellPressure } from "@/lib/scanner";
import { compactUsd } from "@/lib/radar-row";
import { formatCount, formatPrice } from "@/lib/format";
import { formatDate } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { MarketHistoryPage, MarketSnapshot } from "@/types/api";

const PAGE_SIZE = 25;

/**
 * THE OBSERVATION LOG.
 *
 * Append-only, and the page says so: nothing here is ever rewritten, which is
 * what makes the Track Record's claims checkable. Every row is a stored
 * snapshot.
 *
 * The trace above it is drawn from the same page of rows rather than from a
 * separate series — so what is plotted is exactly what is tabulated beneath,
 * and the caption says how many observations that is. No chart library: sixty
 * points need a path, not 40kB.
 *
 * Page 1 shares its query key with the scanner's quick-detail panel, so
 * arriving here from the scanner reuses that cache instead of refetching.
 */
export function HistoryPanel({ mint, className }: { mint: string; className?: string }) {
  const [page, setPage] = useState(1);

  const history = useQuery({
    queryKey: ["tokens", mint, "history", page],
    queryFn: () =>
      api.get<MarketHistoryPage>(
        `/tokens/${mint}/history?page=${page}&page_size=${PAGE_SIZE}`,
      ),
    placeholderData: (previous) => previous,
  });

  // The API returns newest first; a trace reads oldest to newest.
  const trace = useMemo(() => {
    const items = history.data?.items ?? [];
    return items
      .map((row) => Number(row.price_usd ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0)
      .reverse();
  }, [history.data]);

  const columns = useMemo<Column<MarketSnapshot>[]>(
    () => [
      {
        key: "captured",
        header: "Captured",
        width: "160px",
        cell: (row) => (
          <span data-numeric className="text-xs text-ink-3">
            {formatDate(row.captured_at)}
          </span>
        ),
      },
      {
        key: "price",
        header: "Price",
        align: "right",
        width: "104px",
        cell: (row) => (
          <Num value={row.price_usd} display={formatPrice(row.price_usd)} className="text-sm" />
        ),
      },
      {
        key: "marketCap",
        header: "Mkt cap",
        align: "right",
        width: "92px",
        cell: (row) => (
          <Num
            value={row.market_cap}
            display={compactUsd(row.market_cap)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "liquidity",
        header: "Liquidity",
        align: "right",
        width: "92px",
        headerClassName: "hidden sm:table-cell",
        cellClassName: "hidden sm:table-cell",
        cell: (row) => (
          <Num
            value={row.liquidity_usd}
            display={compactUsd(row.liquidity_usd)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "volume",
        header: "Vol 24h",
        align: "right",
        width: "92px",
        headerClassName: "hidden lg:table-cell",
        cellClassName: "hidden lg:table-cell",
        cell: (row) => (
          <Num
            value={row.volume_24h}
            display={compactUsd(row.volume_24h)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "txns",
        header: "Txns",
        align: "right",
        width: "116px",
        srHeader: "Buy and sell transaction counts",
        headerClassName: "hidden lg:table-cell",
        cellClassName: "hidden lg:table-cell",
        cell: (row) => {
          const pressure = buySellPressure(row.buy_count_24h, row.sell_count_24h);
          if (!pressure) {
            return <Num value={null} absentLabel="no transaction counts" />;
          }
          return (
            <span data-numeric className="text-xs">
              <span className="text-up">{formatCount(pressure.buys)}</span>
              <span className="text-ink-4"> / </span>
              <span className="text-down">{formatCount(pressure.sells)}</span>
            </span>
          );
        },
      },
    ],
    [],
  );

  const items = history.data?.items ?? [];
  const pages = history.data?.pages ?? 1;
  const total = history.data?.total ?? 0;

  const first = trace[0];
  const last = trace[trace.length - 1];

  return (
    <section className={cn("flex flex-col gap-3", className)}>
      <header className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div>
          <h2 className="text-sm font-medium tracking-tight text-ink">
            Observation log
          </h2>
          <p className="mt-0.5 text-xs text-ink-3">
            <span data-numeric>{total}</span> stored snapshots. Append-only —
            nothing is ever overwritten.
          </p>
        </div>

        {trace.length > 1 ? (
          <div className="flex items-center gap-3">
            <Sparkline points={trace} width={200} height={36} showArea={false} />
            {first !== undefined && last !== undefined ? (
              <Delta
                value={((last - first) / first) * 100}
                size="md"
              />
            ) : null}
          </div>
        ) : null}
      </header>

      <DataTable
        columns={columns}
        rows={items}
        getRowId={(row) => row.id}
        caption="Every stored market observation for this token, newest first"
        density="compact"
        stickyHeader
        maxHeight="28rem"
        minWidth="460px"
        isPending={history.isPending}
        pendingRows={8}
        empty={
          <p className="px-3 py-8 text-center text-sm text-ink-3">
            No observation has been recorded yet. Once a pool is indexed, every
            refresh appends a snapshot here.
          </p>
        }
      />

      {pages > 1 ? (
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            className={cn(
              "h-7 rounded-md border border-line-control px-2.5 text-xs text-ink-2",
              "transition-colors duration-[var(--duration-instant)]",
              "hover:border-line-strong hover:text-ink",
              "disabled:pointer-events-none disabled:opacity-40",
            )}
          >
            Previous
          </button>
          <span data-numeric className="text-xs text-ink-3">
            {page} / {pages}
          </span>
          <button
            type="button"
            disabled={page >= pages}
            onClick={() => setPage((value) => value + 1)}
            className={cn(
              "h-7 rounded-md border border-line-control px-2.5 text-xs text-ink-2",
              "transition-colors duration-[var(--duration-instant)]",
              "hover:border-line-strong hover:text-ink",
              "disabled:pointer-events-none disabled:opacity-40",
            )}
          >
            Next
          </button>
        </div>
      ) : null}
    </section>
  );
}

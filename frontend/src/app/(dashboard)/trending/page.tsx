"use client";

import { useCallback, useMemo, useState } from "react";

import { TokenCell } from "@/components/scanner/token-cell";
import { DataTable, useTableSort, type Column } from "@/components/ui/data-table";
import { FilterBar, SegmentedControl } from "@/components/ui/filters";
import { FreshnessLabel, LiveStatus, NoMarketData } from "@/components/ui/freshness";
import { Num } from "@/components/ui/num";
import { Toolbar } from "@/components/ui/toolbar";
import { InfoTip } from "@/components/ui/tooltip";
import { ErrorState } from "@/components/ui/states";
import { useTrending } from "@/hooks/use-trending";
import { num } from "@/lib/design/bands";
import { TRENDING_SORT_LABEL, type TrendingSort } from "@/lib/market";
import { buySellPressure } from "@/lib/scanner";
import { compactUsd } from "@/lib/radar-row";
import { formatCount } from "@/lib/format";
import type { TrendingEntry } from "@/types/api";

/**
 * TRENDING — what is drawing market activity right now.
 *
 * WHAT "TRENDING" MEANS HERE, PRECISELY
 *
 * `/market/trending` ranks tokens by one column of their most recent market
 * snapshot: `volume_24h | volume_1h | volume_5m | liquidity_usd | market_cap |
 * price_usd | captured_at`. It computes no momentum, no acceleration, no
 * composite and no attention score.
 *
 * So this screen names its ranking instead of asserting a trend. The toolbar
 * says "Ranked by Volume 24h", not "Hot" — inventing a client-side trend
 * formula would be exactly the unversioned second opinion the rest of this
 * product refuses to hold.
 *
 * WHAT IT CAN SHOW THAT THE SCANNER CANNOT
 *
 * The payload is a full `MarketSnapshot` per token, not the Radar's trimmed
 * `MarketStrip` — so **buy/sell transaction counts are available here**, in the
 * list response, with no extra request. That is the one column Phase 5 had to
 * push into the scanner's detail panel.
 *
 * WHAT IT DELIBERATELY OMITS
 *
 * Score and risk. Both live on `/scores/{mint}` and `/radar/{mint}`, one
 * request each — fifty rows would mean fifty requests to decorate two columns.
 * Tokens here are not necessarily on the Radar at all. The Score column belongs
 * to the Scanner, which is ranked by it; a reader who wants MEMESCOPE's verdict
 * on a token clicks through to its dossier.
 */

const SORT_OPTIONS: { value: TrendingSort; label: string }[] = [
  { value: "volume_24h", label: "Vol 24h" },
  { value: "volume_1h", label: "Vol 1h" },
  { value: "volume_5m", label: "Vol 5m" },
  { value: "liquidity_usd", label: "Liquidity" },
  { value: "market_cap", label: "Mkt cap" },
  { value: "captured_at", label: "Recent" },
];

const LIQUIDITY_OPTIONS = [
  { value: "0", label: "Any" },
  { value: "1000", label: "$1K" },
  { value: "10000", label: "$10K" },
  { value: "50000", label: "$50K" },
];

const AT_SM = "hidden sm:table-cell";
const AT_LG = "hidden lg:table-cell";
const AT_XL = "hidden xl:table-cell";

/** Buy/sell split — transactions, never wallets. */
function TxCell({ entry }: { entry: TrendingEntry }) {
  const pressure = buySellPressure(
    entry.market.buy_count_24h,
    entry.market.sell_count_24h,
  );
  if (!pressure) return <Num value={null} absentLabel="no transaction counts" />;

  return (
    <span className="inline-flex flex-col items-end gap-1">
      <span data-numeric className="text-xs">
        <span className="text-up">{formatCount(pressure.buys)}</span>
        <span className="text-ink-4"> / </span>
        <span className="text-down">{formatCount(pressure.sells)}</span>
      </span>
      <span
        aria-hidden
        className="flex h-0.5 w-full min-w-[3rem] overflow-hidden rounded-full bg-line"
      >
        <span className="bg-up" style={{ width: `${pressure.buyPct}%` }} />
        <span className="bg-down" style={{ width: `${100 - pressure.buyPct}%` }} />
      </span>
      <span className="sr-only">
        {pressure.buys} buy and {pressure.sells} sell transactions in 24 hours
      </span>
    </span>
  );
}

export default function TrendingPage() {
  const [sortBy, setSortBy] = useState<TrendingSort>("volume_24h");
  const [minLiquidity, setMinLiquidity] = useState(0);

  const { data, isPending, isError, refetch } = useTrending({ sortBy, minLiquidity });

  const rows = useMemo(() => data?.items ?? [], [data]);

  const selectValue = useCallback((row: TrendingEntry, key: string) => {
    switch (key) {
      case "price":
        return num(row.market.price_usd);
      case "marketCap":
        return num(row.market.market_cap);
      case "liquidity":
        return num(row.market.liquidity_usd);
      case "volume24":
        return num(row.market.volume_24h);
      case "volume1":
        return num(row.market.volume_1h);
      case "volume5":
        return num(row.market.volume_5m);
      case "txns": {
        const p = buySellPressure(row.market.buy_count_24h, row.market.sell_count_24h);
        return p ? p.total : null;
      }
      default:
        return null;
    }
  }, []);

  // No initial client sort: the server already ordered these, and asserting a
  // second ordering on top would misrepresent which rows are on the page.
  const { sort, setSort, sorted } = useTableSort<TrendingEntry>(rows, selectValue, null);

  const columns = useMemo<Column<TrendingEntry>[]>(
    () => [
      {
        key: "rank",
        header: "#",
        align: "right",
        width: "40px",
        srHeader: "Position in the current ranking",
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
            mint={row.token.mint_address}
            name={row.token.name}
            symbol={row.token.symbol}
            imageUrl={row.token.image_url}
          />
        ),
      },
      {
        key: "price",
        header: "Price",
        align: "right",
        width: "84px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.market.price_usd}
            display={compactUsd(row.market.price_usd)}
            className="text-sm"
          />
        ),
      },
      {
        key: "marketCap",
        header: "Mkt cap",
        align: "right",
        width: "84px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.market.market_cap}
            display={compactUsd(row.market.market_cap)}
            className="text-sm"
          />
        ),
      },
      {
        key: "liquidity",
        header: "Liquidity",
        align: "right",
        width: "84px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.market.liquidity_usd}
            display={compactUsd(row.market.liquidity_usd)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "volume24",
        header: "Vol 24h",
        align: "right",
        width: "84px",
        sortable: true,
        cell: (row) => (
          <Num
            value={row.market.volume_24h}
            display={compactUsd(row.market.volume_24h)}
            className="text-sm"
          />
        ),
      },
      {
        key: "volume1",
        header: "Vol 1h",
        align: "right",
        width: "80px",
        sortable: true,
        headerClassName: AT_LG,
        cellClassName: AT_LG,
        cell: (row) => (
          <Num
            value={row.market.volume_1h}
            display={compactUsd(row.market.volume_1h)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "volume5",
        header: "Vol 5m",
        align: "right",
        width: "80px",
        sortable: true,
        headerClassName: AT_XL,
        cellClassName: AT_XL,
        cell: (row) => (
          <Num
            value={row.market.volume_5m}
            display={compactUsd(row.market.volume_5m)}
            tone="flat"
            className="text-sm"
          />
        ),
      },
      {
        key: "txns",
        header: "Txns 24h",
        align: "right",
        width: "104px",
        sortable: true,
        srHeader: "Buy and sell transaction counts over 24 hours",
        headerClassName: AT_XL,
        cellClassName: AT_XL,
        cell: (row) => <TxCell entry={row} />,
      },
      {
        key: "dex",
        header: "DEX",
        width: "88px",
        headerClassName: AT_XL,
        cellClassName: AT_XL,
        cell: (row) =>
          row.market.dex_name ? (
            <span className="truncate text-xs text-ink-2">{row.market.dex_name}</span>
          ) : (
            <Num value={null} absentLabel="pool not recorded" />
          ),
      },
      {
        key: "data",
        header: "Data",
        width: "76px",
        srHeader: "How old the market reading is",
        headerClassName: AT_SM,
        cellClassName: AT_SM,
        cell: (row) =>
          row.market.captured_at ? (
            <FreshnessLabel capturedAt={row.market.captured_at} className="text-xs" />
          ) : (
            <NoMarketData className="text-xs" />
          ),
      },
    ],
    [],
  );

  return (
    <div className="flex flex-col gap-4">
      <Toolbar
        eyebrow="Trending"
        title="Where the market is active"
        actions={
          <LiveStatus
            timestamps={rows.map((row) => row.market.captured_at)}
            pending={isPending}
          />
        }
        filters={
          <div className="flex flex-col gap-2.5">
            <FilterBar>
              <SegmentedControl
                label="Rank by"
                options={SORT_OPTIONS}
                value={sortBy}
                onChange={(value) => {
                  setSortBy(value);
                  setSort(null);
                }}
              />
              <SegmentedControl
                label="Min liquidity"
                options={LIQUIDITY_OPTIONS}
                value={String(minLiquidity)}
                onChange={(value) => setMinLiquidity(Number(value))}
              />
            </FilterBar>
            <p className="flex items-center gap-1.5 text-xs text-ink-3">
              <span>
                Ranked by <span className="text-ink-2">{TRENDING_SORT_LABEL[sortBy]}</span>
              </span>
              <span aria-hidden className="text-ink-4">
                ·
              </span>
              <span data-numeric>
                {sorted.length} of {data?.total ?? 0}
              </span>
              <InfoTip
                label="the trending ranking"
                content="MEMESCOPE ranks these by one measured column of each token's most recent market snapshot. It is not a momentum or attention score, and it makes no claim that a token is about to move."
              />
            </p>
          </div>
        }
      />

      {isError ? (
        <ErrorState
          body="Trending is not responding. Market snapshots already recorded are safe — this view will recover on its own."
          onRetry={() => void refetch()}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={sorted}
          getRowId={(row) => row.token.mint_address}
          caption="Tokens ranked by their most recent market snapshot"
          sort={sort}
          onSortChange={setSort}
          density="compact"
          stickyHeader
          maxHeight="calc(100dvh - 18rem)"
          minWidth="720px"
          isPending={isPending}
          pendingRows={12}
          empty={
            <div className="px-3 py-12 text-center">
              <p className="text-sm text-ink">Nothing matches this filter</p>
              <p className="mt-1.5 text-xs text-ink-3">
                No token has a recent market snapshot above that liquidity floor.
              </p>
            </div>
          }
        />
      )}
    </div>
  );
}

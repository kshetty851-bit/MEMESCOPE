"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { TokenAvatar } from "@/components/brand/token-avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Metric } from "@/components/ui/metric";
import { Label, Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Sparkline } from "@/components/ui/sparkline";
import { MissionReport } from "@/components/token/mission-report";
import { ApiError, api } from "@/lib/api-client";
import { formatAge, formatCount, formatPrice, formatUsd, shortenAddress } from "@/lib/format";
import { deriveIntelligence } from "@/lib/intelligence";
import { formatDate } from "@/lib/utils";
import type { DiscoveredToken, MarketHistoryPage, TokenMarket } from "@/types/api";

const PAGE_SIZE = 25;

export default function TokenDetailPage() {
  const params = useParams<{ mint: string }>();
  const mint = params.mint;
  const [page, setPage] = useState(1);

  const token = useQuery({
    queryKey: ["tokens", mint],
    queryFn: () => api.get<DiscoveredToken>(`/tokens/${mint}`),
  });

  const market = useQuery({
    queryKey: ["tokens", mint, "market"],
    queryFn: () => api.get<TokenMarket>(`/tokens/${mint}/market`),
    refetchInterval: 30_000,
  });

  const history = useQuery({
    queryKey: ["tokens", mint, "history", page],
    queryFn: () =>
      api.get<MarketHistoryPage>(
        `/tokens/${mint}/history?page=${page}&page_size=${PAGE_SIZE}`,
      ),
    placeholderData: (previous) => previous,
  });

  // Sparkline wants oldest→newest; the API returns newest first.
  const priceTrace = useMemo(() => {
    const items = history.data?.items ?? [];
    return items
      .map((row) => Number(row.price_usd ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0)
      .reverse();
  }, [history.data]);

  if (token.error instanceof ApiError && token.error.status === 404) {
    return (
      <EmptyState
        agent="scout"
        title="Not in the archive"
        body={`${shortenAddress(mint, 8, 8)} has not been discovered by MEMESCOPE. If it launched moments ago, SCOUT may still be resolving it.`}
        action={
          <Link href="/feed">
            <Button variant="outline" size="sm">
              Back to Scanner
            </Button>
          </Link>
        }
      />
    );
  }

  if (token.error) {
    return (
      <ErrorState
        body="The intelligence archive did not respond. The division is still operating."
        onRetry={() => void token.refetch()}
      />
    );
  }

  const snapshot = market.data?.market ?? null;
  const intel = token.data ? deriveIntelligence(token.data, snapshot) : null;

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          <TokenAvatar mint={mint} size={56} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              {token.isPending ? (
                <Skeleton className="h-7 w-48" />
              ) : (
                <h1 className="text-title font-semibold text-ink">
                  {token.data?.name ?? "Unnamed token"}
                </h1>
              )}
              {token.data?.symbol && (
                <span className="rounded-chip bg-elevated px-2 py-0.5 text-sm font-medium text-ink-dim">
                  {token.data.symbol}
                </span>
              )}
              {intel?.elite && (
                <Badge tone="apex">Elite Gem</Badge>
              )}
            </div>
            <p data-numeric className="mt-1.5 truncate text-xs text-ink-faint" title={mint}>
              {mint}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Link href="/feed">
            <Button variant="ghost" size="sm">
              ← Scanner
            </Button>
          </Link>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
        {/* Left: market + history. `min-w-0` is load-bearing — without it the
            720px observation table forces the grid column, and therefore the
            document, wider than the viewport on mobile. */}
        <div className="flex min-w-0 flex-col gap-6">
          <Panel>
            <PanelHeader>
              <div>
                <Label>Current market</Label>
                <PanelTitle className="mt-1">
                  {snapshot
                    ? `Updated ${formatAge(snapshot.captured_at)} ago`
                    : "No pool indexed yet"}
                </PanelTitle>
              </div>
              {snapshot?.dex_name && (
                <Badge tone="plasma">{snapshot.dex_name}</Badge>
              )}
            </PanelHeader>

            {market.isPending ? (
              <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
                {Array.from({ length: 8 }, (_, i) => (
                  <div key={i} className="space-y-2">
                    <Skeleton className="h-2.5 w-16" />
                    <Skeleton className="h-6 w-20" />
                  </div>
                ))}
              </div>
            ) : !snapshot ? (
              <EmptyState
                agent="pulse"
                title="Awaiting first observation"
                body="The provider has not indexed a pool for this mint yet. Enrichment retries on an adaptive schedule — most tokens resolve within minutes."
                className="py-8"
              />
            ) : (
              <>
                {priceTrace.length > 1 && (
                  <div className="mb-6 flex items-end justify-between gap-6 rounded-card bg-abyss/50 p-4">
                    <div>
                      <Label>Price</Label>
                      <p data-numeric className="mt-1 text-3xl font-medium tracking-tight text-ink">
                        {formatPrice(snapshot.price_usd)}
                      </p>
                    </div>
                    <Sparkline
                      points={priceTrace}
                      width={220}
                      height={56}
                      tone={
                        (priceTrace.at(-1) ?? 0) >= (priceTrace[0] ?? 0)
                          ? "var(--color-safe)"
                          : "var(--color-danger)"
                      }
                    />
                  </div>
                )}

                <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
                  <Metric label="Market Cap" value={formatUsd(snapshot.market_cap)} />
                  <Metric label="Liquidity" value={formatUsd(snapshot.liquidity_usd)} />
                  <Metric label="FDV" value={formatUsd(snapshot.fully_diluted_valuation)} />
                  <Metric label="Volume 24h" value={formatUsd(snapshot.volume_24h)} />
                  <Metric label="Volume 1h" value={formatUsd(snapshot.volume_1h)} />
                  <Metric label="Volume 5m" value={formatUsd(snapshot.volume_5m)} />
                  <Metric label="Buys 24h" value={formatCount(snapshot.buy_count_24h)} />
                  <Metric label="Sells 24h" value={formatCount(snapshot.sell_count_24h)} />
                </dl>

                <div className="mt-6 grid gap-3 border-t border-line pt-5 text-sm sm:grid-cols-2">
                  {[
                    { label: "Trading pair", value: snapshot.trading_pair ?? "—" },
                    { label: "Pool", value: shortenAddress(snapshot.pool_address, 6, 6) },
                    { label: "Creator", value: shortenAddress(token.data?.creator_address, 6, 6) },
                    {
                      label: "Discovered",
                      value: token.data ? formatDate(token.data.discovered_at) : "—",
                    },
                    { label: "Snapshots", value: String(market.data?.snapshot_count ?? 0) },
                    { label: "Refresh tier", value: market.data?.tier ?? "—" },
                  ].map((row) => (
                    <div key={row.label} className="flex justify-between gap-4">
                      <span className="text-ink-faint">{row.label}</span>
                      <span data-numeric className="truncate text-ink-dim">
                        {row.value}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Panel>

          {/* History */}
          <Panel density="flush">
            <div className="flex flex-wrap items-center justify-between gap-3 p-6">
              <div>
                <Label>Observation log</Label>
                <PanelTitle className="mt-1 text-heading">
                  {history.data?.total ?? 0} snapshots
                </PanelTitle>
                <p className="mt-1 text-xs text-ink-faint">
                  Append-only. Nothing is ever overwritten.
                </p>
              </div>

              {(history.data?.pages ?? 0) > 1 && (
                <div className="flex items-center gap-2">
                  <Button
                    variant="surface"
                    size="sm"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Previous
                  </Button>
                  <span data-numeric className="text-xs text-ink-faint">
                    {page} / {history.data?.pages ?? 1}
                  </span>
                  <Button
                    variant="surface"
                    size="sm"
                    disabled={page >= (history.data?.pages ?? 1)}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </div>

            <div className="overflow-x-auto border-t border-line">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead>
                  <tr className="border-b border-line/60">
                    {["Captured", "Price", "Market Cap", "Liquidity", "Vol 24h", "Buys / Sells"].map(
                      (head, index) => (
                        <th
                          key={head}
                          scope="col"
                          className={`px-6 py-3 text-label font-medium uppercase text-ink-faint ${index > 0 ? "text-right" : ""}`}
                        >
                          {head}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {history.isPending ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-6">
                        <SkeletonText lines={4} />
                      </td>
                    </tr>
                  ) : (history.data?.items.length ?? 0) === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-6">
                        <EmptyState
                          agent="oracle"
                          title="No observations recorded"
                          body="Once the provider indexes a pool, every refresh appends a snapshot here."
                          className="py-10"
                        />
                      </td>
                    </tr>
                  ) : (
                    history.data?.items.map((row) => (
                      <tr
                        key={row.id}
                        className="border-b border-line/40 transition-colors last:border-0 hover:bg-elevated/40"
                      >
                        <td data-numeric className="px-6 py-3 text-ink-faint">
                          {formatDate(row.captured_at)}
                        </td>
                        <td data-numeric className="px-6 py-3 text-right text-ink">
                          {formatPrice(row.price_usd)}
                        </td>
                        <td data-numeric className="px-6 py-3 text-right text-ink-dim">
                          {formatUsd(row.market_cap)}
                        </td>
                        <td data-numeric className="px-6 py-3 text-right text-ink-dim">
                          {formatUsd(row.liquidity_usd)}
                        </td>
                        <td data-numeric className="px-6 py-3 text-right text-ink-dim">
                          {formatUsd(row.volume_24h)}
                        </td>
                        <td data-numeric className="px-6 py-3 text-right text-ink-faint">
                          {formatCount(row.buy_count_24h)} / {formatCount(row.sell_count_24h)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        {/* Right: mission report */}
        <aside className="flex min-w-0 flex-col gap-6">
          {token.data && intel ? (
            <MissionReport token={token.data} intel={intel} />
          ) : (
            <Panel>
              <SkeletonText lines={8} />
            </Panel>
          )}
        </aside>
      </div>
    </div>
  );
}

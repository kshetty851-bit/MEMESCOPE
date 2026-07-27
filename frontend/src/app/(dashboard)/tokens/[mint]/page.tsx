"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TradingStatusBadge } from "@/components/ui/trading-status-badge";
import { ApiError, api } from "@/lib/api-client";
import {
  formatAge,
  formatCount,
  formatPrice,
  formatUsd,
  shortenAddress,
} from "@/lib/format";
import { formatDate } from "@/lib/utils";
import type { DiscoveredToken, MarketHistoryPage, TokenMarket } from "@/types/api";

const HISTORY_PAGE_SIZE = 25;

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

export default function TokenDetailsPage() {
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
    // Matches the fresh-tier refresh cadence on the backend.
    refetchInterval: 30_000,
  });

  const history = useQuery({
    queryKey: ["tokens", mint, "history", page],
    queryFn: () =>
      api.get<MarketHistoryPage>(
        `/tokens/${mint}/history?page=${page}&page_size=${HISTORY_PAGE_SIZE}`,
      ),
    placeholderData: (previous) => previous,
  });

  if (token.error instanceof ApiError && token.error.status === 404) {
    return (
      <div className="flex flex-col items-center gap-4 py-16 text-center">
        <h1 className="text-xl font-semibold">Token not found</h1>
        <p className="text-sm text-muted">
          <span className="font-mono text-xs">{shortenAddress(mint, 8, 8)}</span> has not
          been discovered by MemeScope.
        </p>
        <Link href="/feed">
          <Button variant="secondary">Back to the feed</Button>
        </Link>
      </div>
    );
  }

  const snapshot = market.data?.market ?? null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold">
              {token.data?.name ?? "Unnamed token"}
            </h1>
            {token.data?.symbol && (
              <span className="rounded bg-surface-raised px-2 py-0.5 text-sm font-medium">
                {token.data.symbol}
              </span>
            )}
            <TradingStatusBadge status={snapshot?.trading_status} />
            {snapshot?.is_verified && (
              <span className="rounded bg-brand/15 px-2 py-0.5 text-xs font-medium text-brand">
                Verified
              </span>
            )}
          </div>
          <p className="font-mono text-xs text-muted" title={mint}>
            {mint}
          </p>
        </div>

        <Link href="/feed">
          <Button variant="secondary" size="sm">
            Back to feed
          </Button>
        </Link>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Current market</CardTitle>
          <CardDescription>
            {snapshot
              ? `Updated ${formatAge(snapshot.captured_at)} ago via ${snapshot.provider}.`
              : "No pool indexed yet — enrichment retries on a schedule."}
          </CardDescription>
        </CardHeader>

        <dl className="grid grid-cols-2 gap-6 sm:grid-cols-3 lg:grid-cols-5">
          <Stat label="Price" value={formatPrice(snapshot?.price_usd)} />
          <Stat label="Market Cap" value={formatUsd(snapshot?.market_cap)} />
          <Stat label="Liquidity" value={formatUsd(snapshot?.liquidity_usd)} />
          <Stat label="FDV" value={formatUsd(snapshot?.fully_diluted_valuation)} />
          <Stat label="Volume 24h" value={formatUsd(snapshot?.volume_24h)} />
          <Stat label="Volume 1h" value={formatUsd(snapshot?.volume_1h)} />
          <Stat label="Volume 5m" value={formatUsd(snapshot?.volume_5m)} />
          <Stat label="Buys 24h" value={formatCount(snapshot?.buy_count_24h)} />
          <Stat label="Sells 24h" value={formatCount(snapshot?.sell_count_24h)} />
          <Stat label="DEX" value={snapshot?.dex_name ?? "—"} />
        </dl>

        <div className="mt-6 grid gap-2 border-t border-border pt-4 text-sm sm:grid-cols-2">
          <div className="flex justify-between gap-4">
            <span className="text-muted">Trading pair</span>
            <span>{snapshot?.trading_pair ?? "—"}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted">Pool address</span>
            <span className="font-mono text-xs" title={snapshot?.pool_address ?? undefined}>
              {shortenAddress(snapshot?.pool_address)}
            </span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted">Creator</span>
            <span
              className="font-mono text-xs"
              title={token.data?.creator_address ?? undefined}
            >
              {shortenAddress(token.data?.creator_address)}
            </span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted">Discovered</span>
            <span>{token.data ? formatDate(token.data.discovered_at) : "—"}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted">Snapshots recorded</span>
            <span className="tabular-nums">{market.data?.snapshot_count ?? 0}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted">Refresh tier</span>
            <span>{market.data?.tier ?? "—"}</span>
          </div>
        </div>
      </Card>

      <Card className="p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-6">
          <div>
            <h2 className="text-lg font-semibold">Snapshot history</h2>
            <p className="text-sm text-muted">
              {history.data?.total ?? 0} observations, newest first. Snapshots are
              append-only — nothing is overwritten.
            </p>
          </div>

          {(history.data?.pages ?? 0) > 1 && (
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                Previous
              </Button>
              <span className="text-xs text-muted">
                Page {page} of {history.data?.pages ?? 1}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={page >= (history.data?.pages ?? 1)}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Captured</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Price</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Market Cap</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Liquidity</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Vol 24h</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Buys/Sells</th>
                <th scope="col" className="px-4 py-3 font-medium">DEX</th>
              </tr>
            </thead>
            <tbody>
              {(history.data?.items.length ?? 0) === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-muted">
                    {history.isPending
                      ? "Loading history…"
                      : "No snapshots recorded yet."}
                  </td>
                </tr>
              ) : (
                history.data?.items.map((row) => (
                  <tr key={row.id} className="border-b border-border/50 last:border-0">
                    <td className="whitespace-nowrap px-4 py-3 text-muted">
                      <time dateTime={row.captured_at}>{formatDate(row.captured_at)}</time>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatPrice(row.price_usd)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatUsd(row.market_cap)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatUsd(row.liquidity_usd)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatUsd(row.volume_24h)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatCount(row.buy_count_24h)} / {formatCount(row.sell_count_24h)}
                    </td>
                    <td className="px-4 py-3">{row.dex_name ?? "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

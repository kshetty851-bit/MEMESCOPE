"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Card } from "@/components/ui/card";
import { TradingStatusBadge } from "@/components/ui/trading-status-badge";
import { useMarketByMint } from "@/hooks/use-market-data";
import { useTokenStream, type StreamStatus } from "@/hooks/use-token-stream";
import { api } from "@/lib/api-client";
import { formatAge, formatUsd, shortenAddress } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DiscoveredToken } from "@/types/api";

const STATUS_LABEL: Record<StreamStatus, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
  offline: "Offline",
};

const STATUS_DOT: Record<StreamStatus, string> = {
  connecting: "bg-muted",
  live: "bg-brand",
  reconnecting: "bg-danger",
  offline: "bg-danger",
};

export default function LiveFeedPage() {
  // Seed from REST so the page is populated on load, then let the socket append.
  const { data: seed } = useQuery({
    queryKey: ["tokens", "latest"],
    queryFn: () => api.get<DiscoveredToken[]>("/tokens/latest?limit=50"),
    staleTime: 10_000,
  });

  const { tokens, status } = useTokenStream(seed ?? []);
  const { byMint } = useMarketByMint();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Live Token Feed</h1>
          <p className="text-sm text-muted">
            Newly launched Solana tokens with market enrichment, newest first.
          </p>
        </div>

        <div className="flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5">
          <span
            aria-hidden
            className={cn(
              "size-2 rounded-full",
              STATUS_DOT[status],
              status === "live" && "animate-pulse",
            )}
          />
          <span className="text-xs font-medium text-muted" role="status">
            {STATUS_LABEL[status]}
          </span>
        </div>
      </div>

      <Card className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1080px] text-left text-sm">
            <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Token</th>
                <th scope="col" className="px-4 py-3 font-medium">Mint</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Market Cap</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Liquidity</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Vol 24h</th>
                <th scope="col" className="px-4 py-3 font-medium">DEX</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Age</th>
              </tr>
            </thead>
            <tbody>
              {tokens.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-muted">
                    {status === "live"
                      ? "Waiting for the next launch…"
                      : "No tokens discovered yet."}
                  </td>
                </tr>
              ) : (
                tokens.map((token) => {
                  const market = byMint.get(token.mint_address);
                  return (
                    <tr
                      key={token.mint_address}
                      className="border-b border-border/50 last:border-0 hover:bg-surface-raised/50"
                    >
                      <td className="max-w-[220px] px-4 py-3">
                        <Link
                          href={`/tokens/${token.mint_address}`}
                          className="flex flex-col hover:text-brand"
                        >
                          <span className="truncate">
                            {token.name ?? <span className="text-muted">Pending…</span>}
                          </span>
                          {token.symbol && (
                            <span className="text-xs text-muted">{token.symbol}</span>
                          )}
                        </Link>
                      </td>

                      <td className="px-4 py-3">
                        <span className="font-mono text-xs" title={token.mint_address}>
                          {shortenAddress(token.mint_address, 5, 5)}
                        </span>
                      </td>

                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatUsd(market?.market_cap)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatUsd(market?.liquidity_usd)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatUsd(market?.volume_24h)}
                      </td>

                      <td className="px-4 py-3">
                        {market?.dex_name ?? <span className="text-muted">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <TradingStatusBadge status={market?.trading_status} />
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-muted">
                        <time dateTime={token.discovered_at}>
                          {formatAge(token.discovered_at)}
                        </time>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

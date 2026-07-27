"use client";

import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/ui/card";
import { useTokenStream, type StreamStatus } from "@/hooks/use-token-stream";
import { api } from "@/lib/api-client";
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

function shorten(address: string | null, lead = 4, tail = 4): string {
  if (!address) return "—";
  if (address.length <= lead + tail + 1) return address;
  return `${address.slice(0, lead)}…${address.slice(-tail)}`;
}

function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

export default function LiveFeedPage() {
  // Seed from REST so the page is populated on load, then let the socket
  // append. Without the seed the feed is blank until the next launch.
  const { data: seed } = useQuery({
    queryKey: ["tokens", "latest"],
    queryFn: () => api.get<DiscoveredToken[]>("/tokens/latest?limit=50"),
    staleTime: 10_000,
  });

  const { tokens, status } = useTokenStream(seed ?? []);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Live Token Feed</h1>
          <p className="text-sm text-muted">
            Newly launched Solana tokens, newest first.
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
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-border text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Mint</th>
                <th scope="col" className="px-4 py-3 font-medium">Name</th>
                <th scope="col" className="px-4 py-3 font-medium">Symbol</th>
                <th scope="col" className="px-4 py-3 font-medium">Discovered</th>
                <th scope="col" className="px-4 py-3 font-medium">Creator</th>
              </tr>
            </thead>
            <tbody>
              {tokens.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-muted">
                    {status === "live"
                      ? "Waiting for the next launch…"
                      : "No tokens discovered yet."}
                  </td>
                </tr>
              ) : (
                tokens.map((token) => (
                  <tr
                    key={token.mint_address}
                    className="border-b border-border/50 last:border-0 hover:bg-surface-raised/50"
                  >
                    <td className="px-4 py-3">
                      <span
                        className="font-mono text-xs text-content"
                        title={token.mint_address}
                      >
                        {shorten(token.mint_address, 6, 6)}
                      </span>
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-3">
                      {token.name ?? <span className="text-muted">Pending…</span>}
                    </td>
                    <td className="px-4 py-3">
                      {token.symbol ? (
                        <span className="rounded bg-surface-raised px-2 py-0.5 text-xs font-medium">
                          {token.symbol}
                        </span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-muted">
                      <time dateTime={token.discovered_at}>
                        {timeAgo(token.discovered_at)}
                      </time>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className="font-mono text-xs text-muted"
                        title={token.creator_address ?? undefined}
                      >
                        {shorten(token.creator_address)}
                      </span>
                    </td>
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

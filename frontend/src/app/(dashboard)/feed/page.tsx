"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { StatusDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AnimatedNumber } from "@/components/ui/metric";
import { Label } from "@/components/ui/panel";
import { SkeletonTokenCard } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";
import { TokenCard } from "@/components/token/token-card";
import { useMarketByMint } from "@/hooks/use-market-data";
import { useTokenStream, type StreamStatus } from "@/hooks/use-token-stream";
import { api } from "@/lib/api-client";
import { deriveIntelligence } from "@/lib/intelligence";
import { cn } from "@/lib/utils";
import type { DiscoveredToken } from "@/types/api";

/**
 * LIVE SCANNER
 *
 * Cards, not a table. A table asks you to compare columns; this feed asks you
 * to notice one thing arriving. New tokens enter at the top with a rise
 * animation so the eye catches motion without the page reflowing under a
 * cursor.
 */

type Filter = "all" | "elite" | "trading" | "risk";

const FILTERS: { id: Filter; label: string; agent?: "apex" | "sentinel" }[] = [
  { id: "all", label: "All discoveries" },
  { id: "elite", label: "Elite Gems", agent: "apex" },
  { id: "trading", label: "Trading" },
  { id: "risk", label: "Flagged", agent: "sentinel" },
];

const STATUS_COPY: Record<StreamStatus, string> = {
  connecting: "Establishing link",
  live: "Feed live",
  reconnecting: "Reconnecting",
  offline: "Offline",
};

export default function LiveScannerPage() {
  const [filter, setFilter] = useState<Filter>("all");

  const { data: seed } = useQuery({
    queryKey: ["tokens", "latest"],
    queryFn: () => api.get<DiscoveredToken[]>("/tokens/latest?limit=60"),
    staleTime: 10_000,
  });

  const { tokens, status } = useTokenStream(seed ?? []);
  const { byMint } = useMarketByMint();

  const decorated = useMemo(
    () =>
      tokens.map((token) => ({
        token,
        market: byMint.get(token.mint_address) ?? null,
        intel: deriveIntelligence(token, byMint.get(token.mint_address) ?? null),
      })),
    [tokens, byMint],
  );

  const visible = useMemo(() => {
    switch (filter) {
      case "elite":
        return decorated.filter((row) => row.intel.elite);
      case "trading":
        return decorated.filter((row) => row.market?.trading_status === "trading");
      case "risk":
        return decorated.filter((row) => row.intel.risk.score >= 0.6);
      default:
        return decorated;
    }
  }, [decorated, filter]);

  const eliteCount = decorated.filter((row) => row.intel.elite).length;

  // Split the feed by observation state. Arrivals are slim rows in their own
  // strip; analysed tokens get full cards. Interleaving them in one grid would
  // leave short cards stretched to tall row heights and read as broken.
  const arrivals = visible.filter((row) => row.intel.provisional).slice(0, 8);
  const analysed = visible.filter((row) => !row.intel.provisional);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Live Scanner</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            Every launch, the moment it happens
          </h1>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-right">
            <Label>In feed</Label>
            <p data-numeric className="text-xl font-medium text-ink">
              <AnimatedNumber value={tokens.length} />
            </p>
          </div>
          <div className="text-right">
            <Label>Elite</Label>
            <p data-numeric className="text-xl font-medium text-apex">
              <AnimatedNumber value={eliteCount} />
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-chip border border-line bg-surface/70 px-3 py-2">
            <StatusDot
              live={status === "live"}
              tone={status === "live" ? "var(--color-safe)" : "var(--color-warn)"}
            />
            <span className="text-label uppercase text-ink-faint">
              {STATUS_COPY[status]}
            </span>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div
        role="tablist"
        aria-label="Filter discoveries"
        className="flex flex-wrap gap-2"
      >
        {FILTERS.map((item) => {
          const active = filter === item.id;
          return (
            <button
              key={item.id}
              role="tab"
              aria-selected={active}
              onClick={() => setFilter(item.id)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-chip border px-3 py-1.5 text-xs transition-colors duration-150",
                active
                  ? "border-plasma/50 bg-plasma/10 text-plasma"
                  : "border-line bg-surface/60 text-ink-faint hover:border-line-bright hover:text-ink",
              )}
            >
              {item.agent && <AgentSigil agent={item.agent} size={13} />}
              {item.label}
            </button>
          );
        })}
      </div>

      {/* Feed */}
      {tokens.length === 0 ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <SkeletonTokenCard key={index} />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          agent={filter === "elite" ? "apex" : "scout"}
          title={
            filter === "elite"
              ? "No Elite Gems right now"
              : "Nothing matches this filter"
          }
          body={
            filter === "elite"
              ? "APEX certifies roughly one token in a hundred. The division is still working — this is the expected state most of the time."
              : "The scanner is still live. Try a different filter, or wait for the next launch."
          }
          action={
            <Button variant="outline" size="sm" onClick={() => setFilter("all")}>
              Show all discoveries
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-8">
          {arrivals.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <Label>Just arrived</Label>
                <span data-numeric className="text-label text-ink-faint">
                  {arrivals.length}
                </span>
              </div>
              <div className="grid gap-2 xl:grid-cols-2">
                {arrivals.map((row, index) => (
                  <TokenCard
                    key={row.token.mint_address}
                    token={row.token}
                    market={row.market}
                    className="animate-[rise_0.4s_var(--ease-instrument)_both]"
                    style={{ animationDelay: `${index * 30}ms` }}
                  />
                ))}
              </div>
            </section>
          )}

          {analysed.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <Label>Analysed</Label>
                <span data-numeric className="text-label text-ink-faint">
                  {analysed.length}
                </span>
              </div>
              <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
                {analysed.map((row, index) => (
                  <TokenCard
                    key={row.token.mint_address}
                    token={row.token}
                    market={row.market}
                    // Stagger only the first screenful; beyond that the delay
                    // would make late cards feel broken, not choreographed.
                    className={
                      index < 9 ? "animate-[rise_0.5s_var(--ease-instrument)_both]" : undefined
                    }
                    style={index < 9 ? { animationDelay: `${index * 40}ms` } : undefined}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

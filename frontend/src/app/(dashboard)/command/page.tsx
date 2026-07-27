"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AiCore } from "@/components/brand/ai-core";
import { AgentSigil } from "@/components/brand/agent-sigil";
import { TokenAvatar } from "@/components/brand/token-avatar";
import { AgentPanel } from "@/components/squad/agent-panel";
import { ObservatoryLog } from "@/components/observatory/observatory-log";
import { TelemetryBar } from "@/components/layout/telemetry-bar";
import { useObservatoryLog } from "@/hooks/use-observatory-log";
import { Badge, StatusDot } from "@/components/ui/badge";
import { AnimatedNumber, Meter } from "@/components/ui/metric";
import { Label, Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton, SkeletonTokenCard } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/states";
import { TokenCard } from "@/components/token/token-card";
import { useMarketByMint } from "@/hooks/use-market-data";
import { useTokenStream } from "@/hooks/use-token-stream";
import { api } from "@/lib/api-client";
import { AGENTS } from "@/lib/design/agents";
import { formatAge, formatUsd } from "@/lib/format";
import { deriveIntelligence } from "@/lib/intelligence";
import type { DiscoveredToken, TokenPage, TrendingPage } from "@/types/api";

/**
 * COMMAND CENTER
 *
 * Three columns, three time horizons: the Core and live discoveries (now), the
 * squad's status (continuous), top opportunities (curated). The right rail is
 * where a user's eye rests between events, so it carries the slowest-changing,
 * highest-value information.
 */
export default function CommandCenterPage() {
  // Seed from REST so landing here shows a populated command view immediately.
  // Without it the page starts empty and fills only as launches happen, which
  // makes a working system look broken for the first minute.
  const { data: seed } = useQuery({
    queryKey: ["tokens", "latest"],
    queryFn: () => api.get<DiscoveredToken[]>("/tokens/latest?limit=40"),
    staleTime: 10_000,
  });

  const { tokens, status } = useTokenStream(seed ?? []);
  const { byMint } = useMarketByMint();

  const totals = useQuery({
    queryKey: ["tokens", "totals"],
    queryFn: () => api.get<TokenPage>("/tokens?page_size=1"),
    refetchInterval: 30_000,
  });

  const trending = useQuery({
    queryKey: ["market", "trending", "command"],
    queryFn: () =>
      api.get<TrendingPage>("/market/trending?sort_by=volume_24h&page_size=6&min_liquidity=500"),
    refetchInterval: 30_000,
  });

  const discovered = totals.data?.total ?? 0;
  const enriched = byMint.size;

  // Elite Gems across whatever the feed currently holds. Recomputed on every
  // tick, which is cheap and keeps the Core honest.
  const elites = useMemo(
    () =>
      tokens.filter(
        (token) => deriveIntelligence(token, byMint.get(token.mint_address) ?? null).elite,
      ),
    [tokens, byMint],
  );

  // Everything the division reports on, computed once per tick.
  const analysis = useMemo(() => {
    const scored = tokens
      .map((token) => ({
        token,
        intel: deriveIntelligence(token, byMint.get(token.mint_address) ?? null),
      }))
      .filter((row) => !row.intel.provisional);

    if (scored.length === 0) {
      return { confidence: 0, whales: 0, threats: 0, topWhale: null as string | null };
    }

    // The Core reflects the division's aggregate conviction across the live
    // window — one number that genuinely moves as the market does.
    const confidence =
      scored.reduce((sum, row) => sum + row.intel.confidence, 0) / scored.length;

    const whaleRows = scored.filter((row) => row.intel.whale.score >= 0.7);
    const threats = scored.filter((row) => row.intel.risk.score >= 0.7).length;

    return {
      confidence,
      whales: whaleRows.length,
      threats,
      topWhale: whaleRows[0]?.token.mint_address ?? null,
    };
  }, [tokens, byMint]);

  // The log is generated from real state transitions and is also what drives
  // the universe reactions — one traversal, two outputs.
  const logEntries = useObservatoryLog(tokens, byMint);

  // Real round-trip latency to the API, sampled rather than continuous.
  const [latency, setLatency] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;

    const sample = async () => {
      const started = performance.now();
      try {
        await api.get<TokenPage>("/tokens?page_size=1");
        if (!cancelled) setLatency(Math.round(performance.now() - started));
      } catch {
        if (!cancelled) setLatency(null);
      }
    };

    void sample();
    const timer = window.setInterval(() => void sample(), 20_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // Lead with tokens the division has actually reported on; arrivals still
  // appear, but a screen of empty cards is a poor first impression.
  const liveTokens = useMemo(() => {
    const analysed = tokens.filter((token) => byMint.has(token.mint_address));
    const arrivals = tokens.filter((token) => !byMint.has(token.mint_address));
    return [...arrivals.slice(0, 2), ...analysed].slice(0, 6);
  }, [tokens, byMint]);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Command Center</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            Solana, under continuous observation
          </h1>
        </div>
      </div>

      <TelemetryBar
        telemetry={{
          coreStatus:
            elites.length > 0
              ? "Elite signal"
              : analysis.confidence > 0.6
                ? "High conviction"
                : "Synthesising",
          signalsToday: discovered,
          eliteGems: elites.length,
          whaleActivity: analysis.whales,
          healthy: status === "live",
          latencyMs: latency,
        }}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        {/* ---------------- Centre: live intelligence ------------------- */}
        <div className="flex min-w-0 flex-col gap-6">
          {/* Core + vitals */}
          <Panel className="overflow-visible">
            <div className="flex flex-col items-center gap-8 md:flex-row">
              <AiCore
                size={260}
                confidence={analysis.confidence}
                elite={elites.length > 0}
                activeAgents={[
                  ...(analysis.whales > 0 ? (["titan"] as const) : []),
                  ...(analysis.threats > 0 ? (["sentinel"] as const) : []),
                ]}
                className="shrink-0"
              />

              <div className="grid flex-1 grid-cols-2 gap-x-6 gap-y-5">
                <div>
                  <Label>Tokens discovered</Label>
                  <p className="mt-1 text-3xl font-medium tracking-tight text-ink">
                    <AnimatedNumber value={discovered} />
                  </p>
                </div>
                <div>
                  <Label>Live market feeds</Label>
                  <p className="mt-1 text-3xl font-medium tracking-tight text-plasma">
                    <AnimatedNumber value={enriched} />
                  </p>
                </div>
                <div>
                  <Label>Elite Gems in feed</Label>
                  <p className="mt-1 text-3xl font-medium tracking-tight text-apex">
                    <AnimatedNumber value={elites.length} />
                  </p>
                </div>
                <div>
                  <Label>Division confidence</Label>
                  <p className="mt-1 text-3xl font-medium tracking-tight text-plasma">
                    <AnimatedNumber
                      value={Math.round(analysis.confidence * 100)}
                      format={(n) => `${Math.round(n)}%`}
                    />
                  </p>
                </div>

                <div className="col-span-2">
                  <Label>Elite gem rate</Label>
                  <Meter
                    value={elites.length / Math.max(tokens.length, 1)}
                    segments={20}
                    tone="var(--color-apex)"
                    className="mt-2"
                    label="Elite gem rate in the current feed"
                  />
                  <p className="mt-2 text-xs text-ink-faint">
                    {elites.length} of {tokens.length} tokens in the live window cleared
                    every check
                  </p>
                </div>
              </div>
            </div>
          </Panel>

          {/* Live discoveries */}
          <div>
            <div className="mb-4 flex items-end justify-between">
              <div>
                <Label>Live discoveries</Label>
                <h2 className="mt-1 text-heading font-medium text-ink">
                  Fresh from the chain
                </h2>
              </div>
              <Link
                href="/feed"
                className="text-xs text-plasma transition-colors hover:text-ink"
              >
                Open Scanner →
              </Link>
            </div>

            {tokens.length === 0 ? (
              <div className="grid gap-4 md:grid-cols-2">
                {Array.from({ length: 4 }, (_, index) => (
                  <SkeletonTokenCard key={index} />
                ))}
              </div>
            ) : (
              <div className="grid items-start gap-4 md:grid-cols-2">
                {liveTokens.map((token) => (
                  <TokenCard
                    key={token.mint_address}
                    token={token}
                    market={byMint.get(token.mint_address) ?? null}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ---------------- Right rail: squad + opportunities ------------ */}
        <aside className="flex min-w-0 flex-col gap-6">
          <section>
            <Label>Intelligence Division</Label>
            <div className="mt-3 flex flex-col gap-3">
              <AgentPanel
                agent="scout"
                status={status === "live" ? "monitoring" : "synchronising"}
                metricLabel="Discovered"
                metricValue={discovered}
                systemLabel="Stream"
                systemValue={status === "live" ? "ONLINE" : "RECONNECTING"}
                recommendation={
                  tokens[0]
                    ? `New signal detected ${formatAge(tokens[0].discovered_at)} ago — ${tokens[0].name ?? "unidentified"}.`
                    : undefined
                }
              />
              <AgentPanel
                agent="titan"
                status={analysis.whales > 0 ? "investigating" : "monitoring"}
                metricLabel="Markets watched"
                metricValue={enriched}
                systemLabel="Capital flow"
                systemValue={analysis.whales > 0 ? "ELEVATED" : "NOMINAL"}
                eventKey={analysis.topWhale ?? undefined}
                recommendation={
                  analysis.whales > 0
                    ? `Whale accumulation confirmed on ${analysis.whales} token${analysis.whales > 1 ? "s" : ""}.`
                    : "No large capital movement in the current window."
                }
              />
              <AgentPanel
                agent="sentinel"
                status={analysis.threats > 0 ? "alert" : "monitoring"}
                metricLabel="Tokens screened"
                metricValue={enriched}
                systemLabel="Threat level"
                systemValue={analysis.threats > 0 ? "ELEVATED" : "NOMINAL"}
                eventKey={analysis.threats > 0 ? `threat-${analysis.threats}` : undefined}
                recommendation={
                  analysis.threats > 0
                    ? `Security concerns detected on ${analysis.threats} token${analysis.threats > 1 ? "s" : ""}.`
                    : "No contract anomalies across screened tokens."
                }
              />
              <AgentPanel
                agent="oracle"
                status={enriched > 0 ? "analysing" : "idle"}
                metricLabel="Tokens scored"
                metricValue={enriched}
                systemLabel="Confidence"
                systemValue={`${Math.round(analysis.confidence * 100)}%`}
                recommendation={
                  elites.length > 0
                    ? `Elite classification granted to ${elites.length} token${elites.length > 1 ? "s" : ""}. Awaiting review.`
                    : "No candidate exceeds classification threshold."
                }
              />
            </div>
            <Link
              href="/division"
              className="mt-3 inline-block text-xs text-plasma transition-colors hover:text-ink"
            >
              View full division →
            </Link>
          </section>

          {/* Top opportunities */}
          <Panel density="flush" className="p-0">
            <div className="p-4">
              <PanelHeader className="mb-0">
                <div>
                  <Label>Top opportunities</Label>
                  <PanelTitle className="mt-1 text-sm">Ranked by 24h volume</PanelTitle>
                </div>
              </PanelHeader>
            </div>

            <div className="border-t border-line">
              {trending.isPending ? (
                <div className="space-y-3 p-4">
                  {Array.from({ length: 4 }, (_, index) => (
                    <Skeleton key={index} className="h-11" />
                  ))}
                </div>
              ) : (trending.data?.items.length ?? 0) === 0 ? (
                <EmptyState
                  agent="pulse"
                  title="No ranked tokens yet"
                  body="PULSE needs at least one enriched market observation before it can rank anything."
                  className="py-10"
                />
              ) : (
                <ul>
                  {trending.data?.items.map((entry) => {
                    const intel = deriveIntelligence(entry.token, entry.market);
                    return (
                      <li key={entry.token.mint_address}>
                        <Link
                          href={`/tokens/${entry.token.mint_address}`}
                          className="flex items-center gap-3 border-b border-line/60 px-4 py-3 transition-colors last:border-0 hover:bg-elevated/50"
                        >
                          <TokenAvatar mint={entry.token.mint_address} size={28} />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm text-ink">
                              {entry.token.symbol ?? entry.token.name ?? "Unnamed"}
                            </p>
                            <p data-numeric className="text-xs text-ink-faint">
                              {formatUsd(entry.market.volume_24h)} vol
                            </p>
                          </div>
                          {intel.elite ? (
                            <AgentSigil agent="apex" size={15} className="text-apex" />
                          ) : (
                            <span
                              data-numeric
                              className="text-xs text-ink-dim"
                              style={{ color: AGENTS.oracle.hue }}
                            >
                              {Math.round(intel.confidence * 100)}%
                            </span>
                          )}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </Panel>

          <ObservatoryLog entries={logEntries} live={status === "live"} />

          {/* System health */}
          <Panel density="compact">
            <Label>System health</Label>
            <ul className="mt-3 flex flex-col gap-2.5">
              {[
                { name: "Discovery scanner", value: status === "live" ? "Operational" : "Degraded", ok: status === "live" },
                { name: "Enrichment worker", value: enriched > 0 ? "Operational" : "Idle", ok: enriched > 0 },
                { name: "Market provider", value: "DexScreener", ok: true },
                { name: "Event stream", value: status === "live" ? "Connected" : "Retrying", ok: status === "live" },
              ].map((row) => (
                <li key={row.name} className="flex items-center justify-between gap-3 text-sm">
                  <span className="flex items-center gap-2 text-ink-dim">
                    <StatusDot
                      live={row.ok}
                      tone={row.ok ? "var(--color-safe)" : "var(--color-warn)"}
                    />
                    {row.name}
                  </span>
                  <span className="text-xs text-ink-faint">{row.value}</span>
                </li>
              ))}
            </ul>
          </Panel>

          <Badge tone="neutral" className="justify-center py-2">
            Signals are heuristics · not financial advice
          </Badge>
        </aside>
      </div>
    </div>
  );
}

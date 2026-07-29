"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";

import { AiCore } from "@/components/brand/ai-core";
import { AgentSigil } from "@/components/brand/agent-sigil";
import { TokenAvatar } from "@/components/brand/token-avatar";
import { AgentPanel } from "@/components/squad/agent-panel";
import { ObservatoryLog } from "@/components/observatory/observatory-log";
import { DashboardPrimer } from "@/components/alpha/dashboard-primer";
import { SentinelPanel } from "@/components/sentinel/sentinel-panel";
import { TelemetryBar } from "@/components/layout/telemetry-bar";
import { useObservatoryLog } from "@/hooks/use-observatory-log";
import { Badge, StatusDot } from "@/components/ui/badge";
import { AnimatedNumber, Meter } from "@/components/ui/metric";
import { Label, Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton, SkeletonTokenCard } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TokenCard } from "@/components/token/token-card";
import { useApiLatency } from "@/hooks/use-api-latency";
import { useMarketByMint } from "@/hooks/use-market-data";
import { useScoresByMint, useTopScores } from "@/hooks/use-scores";
import { useTokenStream } from "@/hooks/use-token-stream";
import { api } from "@/lib/api-client";
import { AGENTS } from "@/lib/design/agents";
import { formatAge } from "@/lib/format";
import { GRADE_LABEL, GRADE_TONE, num } from "@/lib/scores";
import type { DiscoveredToken, TokenPage } from "@/types/api";

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
  const { data: seed, isPending: seedPending } = useQuery({
    queryKey: ["tokens", "latest"],
    queryFn: () => api.get<DiscoveredToken[]>("/tokens/latest?limit=40"),
    staleTime: 10_000,
  });

  const { tokens, status } = useTokenStream(seed ?? []);
  const { byMint } = useMarketByMint();
  // One request for the whole page: the Core, the cards, the log and the rail
  // all read from this shared query rather than fetching per token.
  // `total` is the backend's own count of scored tokens, carried on the same
  // response as the window — Sentinel reports it without a second request.
  const {
    byMint: scoresByMint,
    labelsByMint: scoreLabels,
    total: scoreTotal,
    isPending: scoresPending,
    isError: scoresError,
  } = useScoresByMint();

  const totals = useQuery({
    queryKey: ["tokens", "totals"],
    queryFn: () => api.get<TokenPage>("/tokens?page_size=1"),
    refetchInterval: 30_000,
  });

  // Top opportunities now come from the scoring engine's own ranking rather
  // than from raw volume, which is the whole point of having a score.
  const topScores = useTopScores(6);

  const discovered = totals.data?.total ?? 0;
  const enriched = byMint.size;

  // Elite is a backend certification, not a client calculation: the engine
  // grants it after sustained qualification and the UI only counts what it
  // granted.
  const elites = useMemo(
    () => tokens.filter((token) => scoresByMint.get(token.mint_address)?.is_elite),
    [tokens, scoresByMint],
  );

  // Aggregates over the scores the API served. Every figure below is a count or
  // a mean of backend values — no thresholds are re-derived here.
  const analysis = useMemo(() => {
    const scored = tokens
      .map((token) => scoresByMint.get(token.mint_address))
      .filter((score): score is NonNullable<typeof score> => Boolean(score));

    // `sampled` exists to keep "nothing to measure" distinguishable from
    // "measured zero". The scoring window is the most recently evaluated
    // hundred tokens and the feed is the most recent arrivals; when those two
    // sets do not overlap there is no sample, and rendering that as 0% claimed
    // the division had no confidence rather than no reading.
    if (scored.length === 0) {
      return { confidence: 0, sampled: 0, vetoed: 0, highConviction: 0 };
    }

    const confidence =
      scored.reduce((sum, score) => sum + num(score.evidence.confidence), 0) /
      scored.length /
      100;

    return {
      confidence,
      sampled: scored.length,
      vetoed: scored.filter((score) => score.risk.has_veto).length,
      highConviction: scored.filter(
        (score) => score.grade === "strong" || score.grade === "high_conviction",
      ).length,
    };
  }, [tokens, scoresByMint]);

  // The log is generated from real state transitions and is also what drives
  // the universe reactions — one traversal, two outputs.
  const logEntries = useObservatoryLog(tokens, scoresByMint, scoreLabels);

  // Round-trip latency, sampled from a query the page already runs rather than
  // from a request of its own. The previous implementation fired an extra
  // `/tokens?page_size=1` every 20s purely to time it, which showed up as a
  // duplicate of the totals query on every dashboard load.
  const latency = useApiLatency();

  // "Loading" means a request is genuinely outstanding — not merely that the
  // list is empty. Once both queries have answered, an empty feed is a fact
  // about the chain and should be stated as one.
  const feedLoading = (seedPending || scoresPending) && tokens.length === 0;

  // Lead with tokens the division has actually reported on; arrivals still
  // appear, but a screen of empty cards is a poor first impression.
  const liveTokens = useMemo(() => {
    const analysed = tokens.filter((token) => scoresByMint.has(token.mint_address));
    const arrivals = tokens.filter((token) => !scoresByMint.has(token.mint_address));
    return [...arrivals.slice(0, 2), ...analysed].slice(0, 6);
  }, [tokens, scoresByMint]);

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
          whaleActivity: analysis.vetoed,
          healthy: status === "live",
          latencyMs: latency,
        }}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        {/* ---------------- Centre: live intelligence ------------------- */}
        <div className="flex min-w-0 flex-col gap-6">
          {/* Shown once, above Sentinel: understanding what a score means has to
              come before reading one. */}
          <DashboardPrimer />

          {/* Sentinel leads: the brief is what you read before the numbers.
              It narrates the same `scoresByMint` window the rest of the page
              already has, so it costs no request. */}
          <SentinelPanel
            tokens={tokens}
            scoresByMint={scoresByMint}
            labelsByMint={scoreLabels}
            totalScored={scoresByMint.size > 0 ? scoreTotal : 0}
          />

          {/* Core + vitals */}
          <Panel className="overflow-visible">
            <div className="flex flex-col items-center gap-8 md:flex-row">
              <AiCore
                size={260}
                confidence={analysis.confidence}
                elite={elites.length > 0}
                activeAgents={[
                  ...(analysis.highConviction > 0 ? (["oracle"] as const) : []),
                  ...(analysis.vetoed > 0 ? (["sentinel"] as const) : []),
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
                    {analysis.sampled === 0 ? (
                      <span
                        className="text-ink-faint"
                        title="No scored token in the live feed yet"
                      >
                        —
                      </span>
                    ) : (
                      <AnimatedNumber
                        value={Math.round(analysis.confidence * 100)}
                        format={(n) => `${Math.round(n)}%`}
                      />
                    )}
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

            {/* Three distinct states, deliberately.
                Skeletons used to render whenever the list was empty, which
                meant a failed request and a genuinely quiet chain both looked
                like "still loading" — forever. A first-time user reads that as
                a slow product rather than a broken one, and never reloads. */}
            {scoresError && tokens.length === 0 ? (
              <ErrorState
                body="The intelligence feed is not responding. The division is still scanning — this view will recover on its own once the connection returns."
                onRetry={() => window.location.reload()}
              />
            ) : feedLoading ? (
              <div className="grid gap-4 md:grid-cols-2">
                {Array.from({ length: 4 }, (_, index) => (
                  <SkeletonTokenCard key={index} />
                ))}
              </div>
            ) : tokens.length === 0 ? (
              <EmptyState
                agent="scout"
                title="No launches in this window"
                body="Scout is watching the chain. New tokens appear here the moment they are minted."
              />
            ) : (
              <div className="grid items-start gap-4 md:grid-cols-2">
                {liveTokens.map((token) => (
                  <TokenCard
                    key={token.mint_address}
                    token={token}
                    market={byMint.get(token.mint_address) ?? null}
                    score={scoresByMint.get(token.mint_address) ?? null}
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
                status="idle"
                metricLabel="Markets watched"
                metricValue={enriched}
                systemLabel="Wallet intel"
                systemValue="PENDING"
                recommendation="Awaiting wallet intelligence — smart-money signals are not yet collected."
              />
              <AgentPanel
                agent="sentinel"
                status={analysis.vetoed > 0 ? "alert" : "monitoring"}
                metricLabel="Tokens screened"
                metricValue={scoresByMint.size}
                systemLabel="Threat level"
                systemValue={analysis.vetoed > 0 ? "ELEVATED" : "NOMINAL"}
                eventKey={analysis.vetoed > 0 ? `veto-${analysis.vetoed}` : undefined}
                recommendation={
                  analysis.vetoed > 0
                    ? `Risk gate vetoed ${analysis.vetoed} token${analysis.vetoed > 1 ? "s" : ""} in the current window.`
                    : "No vetoes across scored tokens."
                }
              />
              <AgentPanel
                agent="oracle"
                status={scoresByMint.size > 0 ? "analysing" : "idle"}
                metricLabel="Tokens scored"
                metricValue={scoresByMint.size}
                systemLabel="Confidence"
                systemValue={
                  analysis.sampled === 0 ? "—" : `${Math.round(analysis.confidence * 100)}%`
                }
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
                  <PanelTitle className="mt-1 text-sm">Ranked by AI score</PanelTitle>
                </div>
              </PanelHeader>
            </div>

            <div className="border-t border-line">
              {topScores.isPending ? (
                <div className="space-y-3 p-4">
                  {Array.from({ length: 4 }, (_, index) => (
                    <Skeleton key={index} className="h-11" />
                  ))}
                </div>
              ) : (topScores.data?.items.length ?? 0) === 0 ? (
                <EmptyState
                  agent="oracle"
                  title="No ranked tokens yet"
                  body="ORACLE needs at least one scored token before it can rank anything."
                  className="py-10"
                />
              ) : (
                <ul>
                  {topScores.data?.items.map((entry) => (
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
                          <p
                            className="text-xs"
                            style={{ color: GRADE_TONE[entry.score.grade] }}
                          >
                            {GRADE_LABEL[entry.score.grade]}
                          </p>
                        </div>
                        {entry.score.is_elite ? (
                          <AgentSigil agent="apex" size={15} className="text-apex" />
                        ) : (
                          <span
                            data-numeric
                            className="text-xs"
                            style={{ color: AGENTS.oracle.hue }}
                          >
                            {Math.round(num(entry.score.score))}
                          </span>
                        )}
                      </Link>
                    </li>
                  ))}
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
                {
                  name: "Discovery scanner",
                  value: status === "live" ? "Operational" : "Degraded",
                  ok: status === "live",
                },
                {
                  name: "Enrichment worker",
                  value: enriched > 0 ? "Operational" : "Idle",
                  ok: enriched > 0,
                },
                { name: "Market provider", value: "DexScreener", ok: true },
                {
                  name: "Event stream",
                  value: status === "live" ? "Connected" : "Retrying",
                  ok: status === "live",
                },
              ].map((row) => (
                <li
                  key={row.name}
                  className="flex items-center justify-between gap-3 text-sm"
                >
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

"use client";

import { useQuery } from "@tanstack/react-query";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { AiCore } from "@/components/brand/ai-core";
import { AgentPanel } from "@/components/squad/agent-panel";
import { Badge } from "@/components/ui/badge";
import { Label, Panel } from "@/components/ui/panel";
import { useMarketByMint } from "@/hooks/use-market-data";
import { useScoresByMint } from "@/hooks/use-scores";
import { useTokenStream } from "@/hooks/use-token-stream";
import { api } from "@/lib/api-client";
import { AGENTS, ALL_AGENTS, type AgentId, type AgentStatus } from "@/lib/design/agents";
import { num } from "@/lib/scores";
import type { TokenPage } from "@/types/api";

/**
 * INTELLIGENCE DIVISION
 *
 * The org chart of the organisation. Every specialist's live status, plus the
 * dossier — mission, personality, voice — that makes them a character rather
 * than a metric name.
 */
export default function SquadPage() {
  const { tokens, status } = useTokenStream();
  const { byMint } = useMarketByMint();
  const { byMint: scoresByMint } = useScoresByMint();

  const totals = useQuery({
    queryKey: ["tokens", "totals"],
    queryFn: () => api.get<TokenPage>("/tokens?page_size=1"),
    refetchInterval: 30_000,
  });

  const discovered = totals.data?.total ?? 0;
  const enriched = byMint.size;
  // Every figure below is a count or a mean over scores the API served.
  const scored = tokens
    .map((token) => scoresByMint.get(token.mint_address))
    .filter((score): score is NonNullable<typeof score> => Boolean(score));
  const elites = scored.filter((score) => score.is_elite).length;
  const confidence =
    scored.length > 0
      ? scored.reduce((sum, score) => sum + num(score.evidence.confidence), 0) /
        scored.length /
        100
      : 0;

  const live: {
    agent: AgentId;
    status: AgentStatus;
    metricLabel: string;
    metricValue: number;
    systemLabel: string;
    systemValue: string;
    recommendation: string;
  }[] = [
    {
      agent: "scout",
      status: status === "live" ? "monitoring" : "synchronising",
      metricLabel: "Tokens discovered",
      metricValue: discovered,
      systemLabel: "Stream",
      systemValue: status === "live" ? "ONLINE" : "RETRYING",
      recommendation: "Monitoring mint initialisation across watched launchpads.",
    },
    {
      agent: "titan",
      status: "investigating",
      metricLabel: "Markets watched",
      metricValue: enriched,
      systemLabel: "Wallet index",
      systemValue: "PARTIAL",
      recommendation:
        "Average position size proxies capital flow until wallet clustering is deployed.",
    },
    {
      agent: "pulse",
      status: "analysing",
      metricLabel: "Momentum reads",
      metricValue: enriched,
      systemLabel: "Acceleration",
      systemValue: "ONLINE",
      recommendation: "Comparing five-minute velocity against the 24-hour baseline.",
    },
    {
      agent: "echo",
      status: "learning",
      metricLabel: "Narratives tracked",
      metricValue: enriched,
      systemLabel: "Social feeds",
      systemValue: "PARTIAL",
      recommendation:
        "Participation count stands in for social reach pending narrative ingestion.",
    },
    {
      agent: "sentinel",
      status: "monitoring",
      metricLabel: "Tokens screened",
      metricValue: enriched,
      systemLabel: "Threat level",
      systemValue: "NOMINAL",
      recommendation:
        "Liquidity depth, sell pressure and metadata integrity under continuous review.",
    },
    {
      agent: "oracle",
      status: "analysing",
      metricLabel: "Verdicts issued",
      metricValue: enriched,
      systemLabel: "Confidence engine",
      systemValue: "ONLINE",
      recommendation:
        elites > 0
          ? `Elite classification granted to ${elites} token${elites > 1 ? "s" : ""}.`
          : "No candidate exceeds classification threshold.",
    },
  ];

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Intelligence Division</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            Seven specialists, always on duty
          </h1>
        </div>
        <Badge tone="neutral">Signals are heuristics pending model rollout</Badge>
      </div>

      {/* The Core, with the division orbiting it */}
      <Panel className="flex flex-col items-center gap-8 py-10 lg:flex-row lg:justify-center lg:py-14">
        <AiCore size={300} confidence={confidence} elite={elites > 0} />
        <div className="max-w-sm text-center lg:text-left">
          <Label>The AI Core</Label>
          <h2 className="mt-2 text-heading font-medium text-ink">
            Six analysts feed one brain
          </h2>
          <p className="mt-3 text-sm text-ink-dim">
            Each specialist streams findings into the Core, which integrates them into a
            single confidence score. The Core warms as conviction rises and cools as it
            falls. When every check clears, APEX grants Elite classification and the Core
            emits one golden pulse.
          </p>
        </div>
      </Panel>

      {/* Live status */}
      <section>
        <Label>Live status</Label>
        <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {live.map((entry) => (
            <AgentPanel key={entry.agent} {...entry} />
          ))}
        </div>
      </section>

      {/* Dossiers */}
      <section>
        <Label>Dossiers</Label>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          {ALL_AGENTS.map((id) => {
            const spec = AGENTS[id];
            return (
              <Panel key={id} accent={spec.hue} density="compact">
                <div className="flex gap-4">
                  <div
                    className="flex size-14 shrink-0 items-center justify-center rounded-card border"
                    style={{
                      color: spec.hue,
                      borderColor: `color-mix(in oklch, ${spec.hue} 30%, transparent)`,
                      background: `color-mix(in oklch, ${spec.hue} 9%, transparent)`,
                    }}
                  >
                    <AgentSigil agent={id} size={30} alive />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p
                        className="text-sm font-semibold tracking-[0.14em]"
                        style={{ color: spec.hue }}
                      >
                        {spec.name}
                      </p>
                      {id === "apex" && <Badge tone="apex">Rare</Badge>}
                    </div>
                    <p className="mt-1.5 text-sm text-ink-dim">{spec.mission}</p>

                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {spec.traits.map((trait) => (
                        <span
                          key={trait}
                          className="rounded-chip border border-line bg-elevated/60 px-2 py-0.5 text-[0.6875rem] text-ink-faint"
                        >
                          {trait}
                        </span>
                      ))}
                    </div>

                    <p
                      className="mt-3 border-t border-line pt-3 text-sm italic"
                      style={{ color: spec.hue }}
                    >
                      &ldquo;{spec.voice}&rdquo;
                    </p>
                  </div>
                </div>
              </Panel>
            );
          })}
        </div>
      </section>
    </div>
  );
}

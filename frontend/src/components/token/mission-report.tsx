"use client";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Badge } from "@/components/ui/badge";
import { Meter } from "@/components/ui/metric";
import { Label, Panel } from "@/components/ui/panel";
import { AGENTS, PIPELINE, type AgentId } from "@/lib/design/agents";
import { formatAge } from "@/lib/format";
import { LEVEL_LABEL, type TokenIntelligence } from "@/lib/intelligence";
import { cn } from "@/lib/utils";
import type { DiscoveredToken } from "@/types/api";

/**
 * MISSION REPORT
 *
 * The division's findings as a narrative, in pipeline order, each specialist
 * speaking once in their own voice. A table of the same numbers would be
 * denser and forgettable; the sequence is what makes a verdict feel earned —
 * you watch six independent checks resolve before Oracle scores it.
 */

interface Line {
  agent: AgentId;
  headline: string;
  detail: string;
  score?: number;
  tone?: string;
}

export function MissionReport({
  token,
  intel,
  className,
}: {
  token: DiscoveredToken;
  intel: TokenIntelligence;
  className?: string;
}) {
  const lines: Record<AgentId, Line> = {
    scout: {
      agent: "scout",
      headline: `New signal detected ${formatAge(token.discovered_at)} ago`,
      detail: token.source_program
        ? "Unknown launch discovered at mint initialisation on a watched launchpad."
        : "Unknown launch discovered at mint initialisation.",
    },
    titan: {
      agent: "titan",
      headline: `Capital flow ${LEVEL_LABEL[intel.whale.level].toLowerCase()}`,
      detail: intel.whale.readout,
      score: intel.whale.score,
    },
    pulse: {
      agent: "pulse",
      headline: `Momentum ${LEVEL_LABEL[intel.momentum.level].toLowerCase()}`,
      detail: intel.momentum.readout,
      score: intel.momentum.score,
    },
    echo: {
      agent: "echo",
      headline: `Narrative ${LEVEL_LABEL[intel.community.level].toLowerCase()}`,
      detail: intel.community.readout,
      score: intel.community.score,
    },
    sentinel: {
      agent: "sentinel",
      headline:
        intel.risk.score < 0.25
          ? "Security review cleared"
          : `Risk ${LEVEL_LABEL[intel.risk.level].toLowerCase()}`,
      detail: intel.risk.readout,
      score: intel.risk.score,
      tone: intel.risk.score > 0.5 ? "var(--color-danger)" : undefined,
    },
    oracle: {
      agent: "oracle",
      headline: `Confidence ${Math.round(intel.confidence * 100)}%`,
      detail:
        intel.confidence >= 0.7
          ? "Confidence exceeds historical baseline. Pattern correlation increased across all inputs."
          : intel.confidence >= 0.4
            ? "Inputs are divergent. Correlation below threshold for classification."
            : "Evidence insufficient. No conclusion supported.",
      score: intel.confidence,
    },
    apex: {
      agent: "apex",
      headline: "Elite classification granted",
      detail: "Opportunity verified. All six divisions cleared with conviction and verified depth.",
    },
  };

  return (
    <Panel className={cn("overflow-visible", className)}>
      <div className="mb-5 flex items-center justify-between gap-4">
        <div>
          <Label>Mission report</Label>
          <p className="mt-1 text-heading font-medium text-ink">Division findings</p>
        </div>
        {intel.provisional && <Badge tone="neutral">Awaiting market data</Badge>}
      </div>

      <ol className="relative flex flex-col">
        {/* The spine the whole report hangs from. */}
        <span
          aria-hidden
          className="absolute bottom-6 left-[19px] top-6 w-px bg-gradient-to-b from-scout/40 via-line to-oracle/40"
        />

        {PIPELINE.map((id) => {
          const line = lines[id];
          const spec = AGENTS[id];
          return (
            <li key={id} className="relative flex gap-4 py-3">
              <div
                className="relative z-10 flex size-10 shrink-0 items-center justify-center rounded-full border bg-abyss"
                style={{
                  color: spec.hue,
                  borderColor: `color-mix(in oklch, ${spec.hue} 35%, transparent)`,
                }}
              >
                <AgentSigil agent={id} size={19} alive />
              </div>

              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                  <span
                    className="text-label font-semibold uppercase"
                    style={{ color: spec.hue }}
                  >
                    {spec.name}
                  </span>
                  <span className="text-sm font-medium text-ink">{line.headline}</span>
                </div>
                <p className="mt-1 text-sm text-ink-faint">{line.detail}</p>

                {line.score !== undefined && (
                  <Meter
                    value={line.score}
                    segments={16}
                    tone={line.tone ?? spec.hue}
                    label={`${spec.name} score`}
                    className="mt-2.5 max-w-xs"
                  />
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {/* Apex verdict — the only gold on the page, and only when earned. */}
      <div
        className={cn(
          "relative mt-5 flex items-center gap-4 rounded-card border p-4",
          intel.elite
            ? "reticle border-apex/45 bg-apex/[0.07] text-apex"
            : "border-line bg-abyss/50",
        )}
      >
        <div
          className={cn(
            "flex size-11 shrink-0 items-center justify-center rounded-full border",
            intel.elite
              ? "border-apex/50 bg-apex/10 text-apex"
              : "border-line bg-elevated text-ink-faint",
          )}
        >
          <AgentSigil agent="apex" size={22} alive />
        </div>
        <div className="min-w-0">
          <p
            className={cn(
              "text-sm font-semibold",
              intel.elite ? "text-apex" : "text-ink-dim",
            )}
          >
            {intel.elite
              ? "APEX — Elite classification granted"
              : "APEX — classification withheld"}
          </p>
          <p className="mt-0.5 text-sm text-ink-faint">
            {intel.elite
              ? lines.apex.detail
              : `Elite probability ${Math.round(intel.gemProbability * 100)}%. Classification requires sustained conviction, cleared security review and verified liquidity depth.`}
          </p>
        </div>
      </div>
    </Panel>
  );
}

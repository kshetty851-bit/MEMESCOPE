"use client";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Badge } from "@/components/ui/badge";
import { Meter } from "@/components/ui/metric";
import { Label, Panel } from "@/components/ui/panel";
import { AGENTS, PIPELINE, type AgentId } from "@/lib/design/agents";
import { formatAge } from "@/lib/format";
import { GRADE_LABEL, num, ratio } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { DiscoveredToken } from "@/types/api";
import type { TokenScore } from "@/types/score";

/**
 * MISSION REPORT
 *
 * The division's findings as a narrative, in pipeline order, each specialist
 * speaking once in their own voice. A table of the same numbers would be denser
 * and forgettable; the sequence is what makes a verdict feel earned.
 *
 * Every line is now the backend's. Component scores, their weights and the
 * sentences beneath them come from `/scores/{mint}`, attributed to the agent the
 * API named. A component the model declares but cannot yet evaluate says so
 * explicitly rather than being omitted — that visible gap is the honest reading
 * of a model that is only 65% complete, and hiding it would overstate what the
 * platform knows.
 */

interface Line {
  agent: AgentId;
  headline: string;
  detail: string;
  /** 0–1, when the component reported one. */
  score?: number;
  tone?: string;
}

/** Which agent owns each declared component, per the API's own attribution. */
function linesFor(token: DiscoveredToken, score: TokenScore): Record<AgentId, Line> {
  const byAgent = new Map<string, Line>();

  for (const component of score.components) {
    const agent = component.agent as AgentId;
    if (!(agent in AGENTS)) continue;

    // The engine emits reason codes; the API renders them into sentences. The
    // first is the most significant for that component.
    const detail = component.reasons.length
      ? (score.reasons.find((reason) => component.reasons.includes(reason.code))?.message ??
        component.reasons[0])
      : undefined;

    if (!component.available) {
      // Declared with real weight but no data source yet. Saying so is what
      // makes the missing signal visible in the product rather than silently
      // absent from a weight table.
      //
      // An agent can own several components — Sentinel holds both liquidity
      // depth and contract safety — so an unavailable one must never overwrite
      // a reading that exists. Without this guard Sentinel reported "not yet
      // available" on a token whose liquidity it had actually measured.
      if (byAgent.has(agent)) continue;
      byAgent.set(agent, {
        agent,
        headline: "Signal not yet available",
        detail: `Declared at ${Math.round(num(component.declared_weight) * 100)}% of the model. No data source for this signal yet.`,
      });
      continue;
    }

    const value = num(component.score);
    byAgent.set(agent, {
      agent,
      headline: `${labelOf(component.id)} ${Math.round(value)}`,
      detail: detail ?? `Contributing ${num(component.contribution).toFixed(2)} points.`,
      score: value / 100,
      tone:
        component.id === "market_risk" || value < 35 ? "var(--color-danger)" : undefined,
    });
  }

  const confidence = num(score.evidence.confidence);

  return {
    scout: byAgent.get("scout") ?? {
      agent: "scout",
      headline: `New signal detected ${formatAge(token.discovered_at)} ago`,
      detail: "Discovered at mint initialisation on a watched launchpad.",
    },
    titan: byAgent.get("titan") ?? {
      agent: "titan",
      headline: "Signal not yet available",
      detail: "Wallet intelligence is not yet collected.",
    },
    pulse: byAgent.get("pulse") ?? {
      agent: "pulse",
      headline: "No flow to measure",
      detail: "No trade activity recorded in the current window.",
    },
    echo: byAgent.get("echo") ?? {
      agent: "echo",
      headline: "Signal not yet available",
      detail: "Narrative tracking is not yet collected.",
    },
    // Sentinel always speaks for the risk gate, never for a weighted component.
    // The gate is not part of the sum at all — it multiplies the composite and
    // can veto it outright — so it is the one thing Sentinel must report.
    sentinel: {
      agent: "sentinel",
      headline: score.risk.has_veto ? "Risk gate engaged" : "No anomalies recorded",
      detail: score.risk.has_veto
        ? "The score was capped regardless of every other signal."
        : `Market risk ${Math.round(num(score.risk.market_risk))} of 100.`,
      score: ratio(score.risk.market_risk),
      tone: num(score.risk.market_risk) > 50 ? "var(--color-danger)" : undefined,
    },
    oracle: {
      agent: "oracle",
      headline: `${GRADE_LABEL[score.grade]} — score ${Math.round(num(score.score))}`,
      detail: `Confidence ${Math.round(confidence)}% from ${score.evidence.observations} observations at ${Math.round(num(score.evidence.coverage))}% model coverage. Model ${score.model_version}.`,
      score: ratio(score.score),
    },
    apex: {
      agent: "apex",
      headline: "Elite classification granted",
      detail: "Sustained conviction, cleared risk gate and verified liquidity depth.",
    },
  };
}

/** Component ids as short headlines. Presentation only. */
function labelOf(id: string): string {
  return id
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function MissionReport({
  token,
  score,
  className,
}: {
  token: DiscoveredToken;
  /** Null until the engine has scored this token. */
  score: TokenScore | null;
  className?: string;
}) {
  if (!score) {
    return (
      <Panel className={cn("overflow-visible", className)}>
        <div className="mb-5 flex items-center justify-between gap-4">
          <div>
            <Label>Mission report</Label>
            <p className="mt-1 text-heading font-medium text-ink">Division findings</p>
          </div>
          <Badge tone="neutral">Awaiting score</Badge>
        </div>
        <p className="text-sm text-ink-faint">
          The division has not reported on this token yet. Findings appear once the scoring
          engine has evaluated its first market observation.
        </p>
      </Panel>
    );
  }

  const lines = linesFor(token, score);
  const elite = score.is_elite;

  return (
    <Panel className={cn("overflow-visible", className)}>
      <div className="mb-5 flex items-center justify-between gap-4">
        <div>
          <Label>Mission report</Label>
          <p className="mt-1 text-heading font-medium text-ink">Division findings</p>
        </div>
        {score.risk.has_veto && <Badge tone="danger">Vetoed</Badge>}
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
          elite
            ? "reticle border-apex/45 bg-apex/[0.07] text-apex"
            : "border-line bg-abyss/50",
        )}
      >
        <div
          className={cn(
            "flex size-11 shrink-0 items-center justify-center rounded-full border",
            elite
              ? "border-apex/50 bg-apex/10 text-apex"
              : "border-line bg-elevated text-ink-faint",
          )}
        >
          <AgentSigil agent="apex" size={22} alive />
        </div>
        <div className="min-w-0">
          <p className={cn("text-sm font-semibold", elite ? "text-apex" : "text-ink-dim")}>
            {elite
              ? "APEX — Elite classification granted"
              : "APEX — classification withheld"}
          </p>
          <p className="mt-0.5 text-sm text-ink-faint">
            {elite
              ? lines.apex.detail
              : `Score ${Math.round(num(score.score))}, evidence ${Math.round(
                  num(score.evidence.evidence),
                )}%. Classification requires sustained conviction, a cleared risk gate and verified liquidity depth.`}
          </p>
        </div>
      </div>
    </Panel>
  );
}

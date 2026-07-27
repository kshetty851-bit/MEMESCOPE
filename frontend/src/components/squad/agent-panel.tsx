"use client";

import { useEffect, useRef, useState } from "react";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { AnimatedNumber } from "@/components/ui/metric";
import { Label, Panel } from "@/components/ui/panel";
import {
  AGENTS,
  STATUS_LABEL,
  STATUS_TONE,
  isActive,
  type AgentId,
  type AgentStatus,
} from "@/lib/design/agents";
import { cn } from "@/lib/utils";

/**
 * Specialist profile card.
 *
 * Every member of the division reports in the same four-part structure —
 * status, primary count, secondary system, recommendation — so a user learns
 * the shape once and can then read any specialist at a glance.
 *
 * Status sits directly beneath the sigil, where the eye already is.
 */
export function AgentPanel({
  agent,
  status,
  metricLabel,
  metricValue,
  systemLabel,
  systemValue,
  recommendation,
  /** Bump this to fire one ripple — a whale event, a security flag. */
  eventKey,
  className,
}: {
  agent: AgentId;
  status: AgentStatus;
  metricLabel: string;
  metricValue: number;
  systemLabel: string;
  systemValue: string;
  recommendation?: string;
  eventKey?: string | number;
  className?: string;
}) {
  const spec = AGENTS[agent];
  const active = isActive(status);
  const statusTone = STATUS_TONE[status] ?? spec.hue;

  // Single-shot event ripple. Keyed off a change in `eventKey` so re-renders
  // during a sustained event do not re-fire it — a specialist that pulses
  // continuously reads as broken, not urgent.
  const [ripple, setRipple] = useState(0);
  const lastEvent = useRef(eventKey);
  useEffect(() => {
    if (eventKey !== undefined && eventKey !== lastEvent.current) {
      setRipple((n) => n + 1);
    }
    lastEvent.current = eventKey;
  }, [eventKey]);

  return (
    <Panel
      accent={spec.hue}
      density="compact"
      className={cn("group", className)}
      data-agent={agent}
    >
      <div className="flex items-start gap-3">
        <div className="relative flex flex-col items-center gap-1.5">
          <div
            className="relative flex size-10 shrink-0 items-center justify-center rounded-card border"
            style={{
              color: spec.hue,
              borderColor: `color-mix(in oklch, ${spec.hue} 32%, transparent)`,
              background: `color-mix(in oklch, ${spec.hue} 10%, transparent)`,
            }}
          >
            <AgentSigil agent={agent} size={22} alive />

            {active && (
              <span
                aria-hidden
                className="ambient absolute inset-0 rounded-card animate-[breathe_6s_ease-in-out_infinite]"
                style={{
                  boxShadow: `0 0 16px color-mix(in oklch, ${spec.hue} 40%, transparent)`,
                }}
              />
            )}

            {/* Event ripple: one expanding ring in the specialist's own hue,
                or danger red when Sentinel raises an alert. */}
            {ripple > 0 && (
              <span
                key={ripple}
                aria-hidden
                className="ambient pointer-events-none absolute inset-0 rounded-card border-2"
                style={{
                  borderColor: statusTone,
                  animation: "ripple-once 1.6s var(--ease-instrument) forwards",
                }}
              />
            )}
          </div>

          {/* Status, directly beneath the sigil. */}
          <span
            className="text-[0.5625rem] uppercase tracking-[0.1em] whitespace-nowrap"
            style={{ color: statusTone }}
          >
            {STATUS_LABEL[status]}
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <p
            className="text-sm font-semibold tracking-[0.12em]"
            style={{ color: spec.hue }}
          >
            {spec.name}
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">{spec.mission}</p>
        </div>
      </div>

      <div className="mt-4 flex items-end justify-between gap-3">
        <div>
          <Label>{metricLabel}</Label>
          <p className="mt-0.5 text-xl font-medium text-ink">
            <AnimatedNumber value={metricValue} />
          </p>
        </div>
        <div className="text-right">
          <Label>{systemLabel}</Label>
          <p
            data-numeric
            className="mt-0.5 text-xs font-medium"
            style={{ color: spec.hue }}
          >
            {systemValue}
          </p>
        </div>
      </div>

      {recommendation && (
        <p className="mt-3 border-t border-line pt-3 text-xs leading-relaxed text-ink-dim">
          {recommendation}
        </p>
      )}
    </Panel>
  );
}

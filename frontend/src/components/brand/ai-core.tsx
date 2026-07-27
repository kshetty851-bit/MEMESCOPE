"use client";

import { useEffect, useId, useRef, useState } from "react";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { AGENTS, PIPELINE, type AgentId } from "@/lib/design/agents";
import { cn } from "@/lib/utils";

/**
 * THE AI CORE
 *
 * The emotional centre of the product, and the one element permitted to react
 * to the state of the whole system.
 *
 * Six specialists orbit and continuously feed it. As aggregate confidence
 * rises the Core *warms*: it brightens, more data rings activate, more packets
 * travel the feed lines, and its pulse quickens — all subtly, all within the
 * house motion language. As confidence falls it cools back down. When Apex
 * grants Elite classification it emits exactly one golden pulse, never a
 * repeating celebration.
 *
 * Built from SVG and CSS animation rather than canvas or WebGL on purpose: it
 * must hold 60fps on a laptop that is also running a WebSocket feed, degrade
 * to a still image under `prefers-reduced-motion`, vanish in Command mode, and
 * cost nothing in bundle size. Every reactive property is driven through CSS
 * custom properties so a confidence change repaints without re-rendering React.
 */

export interface AiCoreProps {
  size?: number;
  /** Aggregate confidence, 0–1. Drives brightness, rings, particles and tempo. */
  confidence?: number;
  /** Apex has granted Elite classification. Fires one golden emission. */
  elite?: boolean;
  /** Renders the six orbiting specialists. Off for compact placements. */
  showAgents?: boolean;
  /** Specialists currently reporting an event, rendered with a brief flare. */
  activeAgents?: AgentId[];
  className?: string;
  label?: string;
}

const CENTRE = 200;
const ORBIT = 148;

export function AiCore({
  size = 320,
  confidence = 0.5,
  elite = false,
  showAgents = true,
  activeAgents,
  className,
  label,
}: AiCoreProps) {
  const uid = useId().replace(/:/g, "");
  const level = Math.max(0, Math.min(1, confidence));

  // Rings activate progressively: one at rest, four at full conviction. This is
  // the clearest read of "the Core is synthesising more" at a glance.
  const activeRings = 1 + Math.round(level * 3);
  // Packet density scales with conviction, capped so the feed never looks busy.
  const packetsPerFeed = level > 0.66 ? 2 : 1;
  // Tempo: 7.4s when cool, 4.2s at full conviction. Faster, never frantic.
  const pulseSeconds = (7.4 - level * 3.2).toFixed(2);
  // Brightness rides opacity rather than a filter — filters force a repaint of
  // the whole subtree on every change.
  const glow = 0.55 + level * 0.45;

  const accent = elite ? "var(--color-apex)" : "var(--color-plasma)";

  // Single-shot gold. Keyed off the false→true transition so re-renders while
  // an Elite Gem is on screen do not re-fire it.
  const [emission, setEmission] = useState(0);
  const wasElite = useRef(elite);
  useEffect(() => {
    if (elite && !wasElite.current) setEmission((n) => n + 1);
    wasElite.current = elite;
  }, [elite]);

  return (
    <div
      className={cn("relative select-none", className)}
      style={
        {
          width: size,
          height: size,
          "--core-glow": glow,
          "--core-tempo": `${pulseSeconds}s`,
        } as React.CSSProperties
      }
      role="img"
      aria-label={
        label ??
        (elite
          ? "AI Core — Elite classification granted"
          : `AI Core synthesising intelligence, confidence ${Math.round(level * 100)} percent`)
      }
    >
      <svg viewBox="0 0 400 400" className="size-full overflow-visible">
        <defs>
          <radialGradient id={`${uid}-plasma`}>
            <stop offset="0%" stopColor={accent} stopOpacity="0.95" />
            <stop
              offset="45%"
              stopColor={elite ? "var(--color-apex)" : "var(--color-plasma-deep)"}
              stopOpacity="0.35"
            />
            <stop offset="100%" stopColor="transparent" stopOpacity="0" />
          </radialGradient>

          <radialGradient id={`${uid}-halo`}>
            <stop offset="60%" stopColor="transparent" />
            <stop offset="100%" stopColor={accent} stopOpacity="0.18" />
          </radialGradient>

          <filter id={`${uid}-bloom`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <circle cx={CENTRE} cy={CENTRE} r="190" fill={`url(#${uid}-halo)`} />

        {/* Data rings. Counter-rotating so the assembly reads as machinery
            rather than a spinning logo; the count is the confidence readout. */}
        {[
          { r: ORBIT, dur: 60, dash: "1 9", width: 1 },
          { r: 112, dur: 44, dash: "34 14", width: 1 },
          { r: 92, dur: 78, dash: "3 12", width: 0.75 },
          { r: 132, dur: 96, dash: "18 26", width: 0.75 },
        ].map((ring, index) => {
          const on = index < activeRings;
          return (
            <g
              key={ring.r}
              // Driven by inline style, not a utility class: Tailwind cannot
              // statically extract a class built from a runtime duration.
              className="motion-loop origin-center"
              style={{
                animation: `orbit ${ring.dur}s linear infinite${index % 2 ? " reverse" : ""}`,
                transformOrigin: "center",
              }}
            >
              <circle
                cx={CENTRE}
                cy={CENTRE}
                r={ring.r}
                fill="none"
                stroke={index < 2 ? "var(--color-line-bright)" : accent}
                strokeWidth={ring.width}
                strokeDasharray={ring.dash}
                // Rings fade in rather than pop, so a confidence change reads
                // as the Core warming rather than as a UI state flip.
                opacity={on ? (index < 2 ? 0.5 : 0.3) : 0}
                style={{ transition: "opacity 1.2s var(--ease-precise)" }}
              />
            </g>
          );
        })}

        {/* Feed lines: each specialist streams into the centre. */}
        {showAgents &&
          PIPELINE.map((id, index) => {
            const angle = (index / PIPELINE.length) * Math.PI * 2 - Math.PI / 2;
            const x = CENTRE + Math.cos(angle) * ORBIT;
            const y = CENTRE + Math.sin(angle) * ORBIT;
            const flaring = activeAgents?.includes(id);

            return (
              <g key={id}>
                <line
                  x1={x}
                  y1={y}
                  x2={CENTRE}
                  y2={CENTRE}
                  stroke={AGENTS[id].hue}
                  strokeWidth={flaring ? 1.6 : 1}
                  opacity={flaring ? 0.55 : 0.18 + level * 0.14}
                  style={{ transition: "opacity 0.8s var(--ease-precise)" }}
                />
                {Array.from({ length: packetsPerFeed }, (_, packet) => (
                  <circle
                    key={packet}
                    r={2.5}
                    fill={AGENTS[id].hue}
                    className="ambient"
                  >
                    <animate
                      attributeName="cx"
                      values={`${x};${CENTRE}`}
                      dur={`${pulseSeconds}s`}
                      begin={`${index * 0.5 + packet * Number(pulseSeconds) * 0.5}s`}
                      repeatCount="indefinite"
                    />
                    <animate
                      attributeName="cy"
                      values={`${y};${CENTRE}`}
                      dur={`${pulseSeconds}s`}
                      begin={`${index * 0.5 + packet * Number(pulseSeconds) * 0.5}s`}
                      repeatCount="indefinite"
                    />
                    <animate
                      attributeName="opacity"
                      values="0;1;1;0"
                      dur={`${pulseSeconds}s`}
                      begin={`${index * 0.5 + packet * Number(pulseSeconds) * 0.5}s`}
                      repeatCount="indefinite"
                    />
                  </circle>
                ))}
              </g>
            );
          })}

        {/* Core body */}
        <circle
          cx={CENTRE}
          cy={CENTRE}
          r="78"
          fill={`url(#${uid}-plasma)`}
          filter={`url(#${uid}-bloom)`}
          opacity={glow}
          className="motion-loop origin-center"
          style={{
            animation: `breathe var(--core-tempo) ease-in-out infinite`,
            transformOrigin: "center",
            transition: "opacity 1.2s var(--ease-precise)",
          }}
        />
        <circle
          cx={CENTRE}
          cy={CENTRE}
          r="46"
          fill="none"
          stroke={accent}
          strokeWidth="1.5"
          opacity={0.45 + level * 0.35}
          strokeDasharray="60 18"
          className="motion-loop origin-center"
          style={{
            animation: "core 8s ease-in-out infinite",
            transformOrigin: "center",
            transition: "opacity 1.2s var(--ease-precise)",
          }}
        />
        <circle
          cx={CENTRE}
          cy={CENTRE}
          r={18 + level * 6}
          fill={accent}
          opacity={0.75 + level * 0.25}
          filter={`url(#${uid}-bloom)`}
          style={{ transition: "r 1.2s var(--ease-instrument), opacity 1.2s var(--ease-precise)" }}
        />

        {/* Elite emission — one golden pulse, then silence. */}
        {emission > 0 && (
          <circle
            key={emission}
            cx={CENTRE}
            cy={CENTRE}
            r="78"
            fill="none"
            stroke="var(--color-apex)"
            strokeWidth="2"
            className="ambient origin-center"
            style={{
              animation: "emit-gold 2.2s var(--ease-instrument) forwards",
              transformOrigin: "center",
            }}
          />
        )}
      </svg>

      {/* Specialist nodes, over the SVG so they can carry real markup. */}
      {showAgents &&
        PIPELINE.map((id, index) => {
          const angle = (index / PIPELINE.length) * Math.PI * 2 - Math.PI / 2;
          const x = 50 + (Math.cos(angle) * ORBIT * 100) / 400;
          const y = 50 + (Math.sin(angle) * ORBIT * 100) / 400;
          const flaring = activeAgents?.includes(id);

          return (
            <div
              key={id}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${x}%`, top: `${y}%`, color: AGENTS[id].hue }}
            >
              <div
                className={cn(
                  "motion-loop flex size-9 items-center justify-center rounded-full border bg-abyss/80 backdrop-blur-sm",
                  flaring ? "border-current" : "border-current/40",
                )}
                style={{
                  animation: `breathe var(--core-tempo) ease-in-out infinite`,
                  animationDelay: `${index * 0.7}s`,
                  boxShadow: flaring
                    ? `0 0 18px color-mix(in oklch, ${AGENTS[id].hue} 55%, transparent)`
                    : undefined,
                  transition: "box-shadow 0.6s var(--ease-precise)",
                }}
              >
                <AgentSigil agent={id} size={18} alive />
              </div>
            </div>
          );
        })}
    </div>
  );
}

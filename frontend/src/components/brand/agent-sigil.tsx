import type { AgentId } from "@/lib/design/agents";
import { cn } from "@/lib/utils";

/**
 * Specialist sigils.
 *
 * Deliberately *not* mascot illustrations. Each creature is reduced to a
 * geometric sigil built from arcs, nodes and hairlines — the same visual
 * grammar as an instrument dial or a constellation chart. Drawn on a 48×48
 * grid with 1.5px strokes so they stay crisp from 12px to 200px, and coloured
 * entirely by `currentColor` so one component serves every context.
 *
 * A cartoon frog would date instantly and read as a meme coin project. A sigil
 * reads as an institution.
 *
 * IDLE BEHAVIOUR (`alive`)
 * At display sizes the sigils gain the idle layer: eyes blink, visors glow,
 * energy travels the armour, sensors sweep. Every behaviour is CSS on
 * `transform`, `opacity` or `stroke-dashoffset` — all compositor-only — and
 * every one is tagged `.motion-loop`, so Command mode and reduced motion still
 * them without removing the emblem.
 *
 * The idle layer is off by default: a 12px sigil inside a badge should not be
 * blinking, and a feed of sixty cards must not run sixty animations.
 */

interface SigilParts {
  /** Structural geometry, always drawn. */
  base: React.ReactNode;
  /** Idle-only layer: blinking eyes, visor glow, sensor sweep. */
  alive?: (uid: string) => React.ReactNode;
}

/** Energy conduits: a dashed path that flows when alive. */
function conduit(d: string, alive: boolean, duration = 4) {
  return (
    <path
      d={d}
      strokeDasharray="6 36"
      className={alive ? "motion-loop" : undefined}
      style={alive ? { animation: `energy ${duration}s linear infinite` } : undefined}
      opacity="0.75"
    />
  );
}

function eye(cx: number, cy: number, r: number, alive: boolean, delay: number) {
  return (
    <circle
      cx={cx}
      cy={cy}
      r={r}
      fill="currentColor"
      stroke="none"
      className={alive ? "motion-loop" : undefined}
      style={
        alive
          ? {
              animation: `blink 7s ease-in-out infinite`,
              animationDelay: `${delay}s`,
              transformOrigin: `${cx}px ${cy}px`,
            }
          : undefined
      }
    />
  );
}

function PARTS(agent: AgentId, alive: boolean): SigilParts {
  switch (agent) {
    // Wide-set eyes over a leaping arc — a frog at rest, mid-detection.
    case "scout":
      return {
        base: (
          <>
            <circle cx="18" cy="17" r="4.2" />
            <circle cx="30" cy="17" r="4.2" />
            {eye(18, 17, 1.3, alive, 0)}
            {eye(30, 17, 1.3, alive, 0.12)}
            <path d="M13 25c3.4 4.6 7 6.9 11 6.9s7.6-2.3 11-6.9" />
            <path d="M12 30l-4 6M36 30l4 6" />
            {conduit("M24 32v6", alive, 3.4)}
          </>
        ),
      };

    // Concentric holographic eyes beneath a brow arc — the owl, all perception.
    case "oracle":
      return {
        base: (
          <>
            <path d="M9 18c0-6 6.7-10 15-10s15 4 15 10" />
            <circle cx="17.5" cy="24" r="6.5" />
            <circle cx="30.5" cy="24" r="6.5" />
            <circle cx="17.5" cy="24" r="2.6" />
            <circle cx="30.5" cy="24" r="2.6" />
            {eye(17.5, 24, 1, alive, 0)}
            {eye(30.5, 24, 1, alive, 0.08)}
            <path d="M24 30.5l-2.4 4h4.8z" fill="currentColor" stroke="none" />
            <path d="M13 37c3 2.4 7 3.6 11 3.6S32 39.4 35 37" opacity="0.5" />
          </>
        ),
        // Analysis ring sweeping the lenses.
        alive: () => (
          <circle
            cx="24"
            cy="24"
            r="15"
            strokeDasharray="3 8"
            opacity="0.4"
            className="motion-loop"
            style={{ animation: "orbit 22s linear infinite", transformOrigin: "24px 24px" }}
          />
        ),
      };

    // A vast body arc closing into a fluke, with a data spout rising.
    case "titan":
      return {
        base: (
          <>
            <path d="M7 27c5-9 13-13.5 22-13.5 6.5 0 11 2.4 13 6" />
            <path d="M7 27c4.5 7.5 11.6 11.3 20 11.3 5.6 0 10-1.5 13-4.4" />
            <path d="M40 33.9l3.5 5.6-7-1.4 3.5-4.2z" fill="currentColor" stroke="none" />
            {eye(15, 24, 1.5, alive, 0.3)}
            {conduit("M17 13.5l-1.5-5M23 12l.5-6M29 13.5l2.5-5", alive, 5)}
          </>
        ),
      };

    // A dorsal fin cutting a waveform — predator and price chart in one mark.
    case "pulse":
      return {
        base: (
          <>
            <path d="M24 6l9 21H15z" />
            <path d="M6 33h6l4-7 5 12 5-16 4 11h12" />
            {eye(24, 19, 1.6, alive, 0.5)}
            <path d="M18 41h12" opacity="0.45" />
          </>
        ),
        // Sensor sweep across the waveform.
        alive: (uid) => (
          <g clipPath={`url(#${uid}-clip)`}>
            <defs>
              <clipPath id={`${uid}-clip`}>
                <rect x="4" y="28" width="40" height="10" />
              </clipPath>
            </defs>
            <rect
              x="4"
              y="31"
              width="40"
              height="1.5"
              fill="currentColor"
              stroke="none"
              className="motion-loop"
              style={{ animation: "sweep 5s ease-in-out infinite" }}
            />
          </g>
        ),
      };

    // A guardian coil tightening to a diamond head. Stillness, then strike.
    case "sentinel":
      return {
        base: (
          <>
            <path d="M24 41c-8.5 0-14-4.6-14-10.4S15 21 22.5 21s11.5 3.2 11.5 7.4-3.6 6-8 6-6.6-2-6.6-4" />
            <path d="M31 7l6 5-6 5-6-5z" />
            {conduit("M31 17v4", alive, 3)}
            {eye(29, 11.4, 0.9, alive, 0.2)}
            {eye(33, 11.4, 0.9, alive, 0.2)}
          </>
        ),
        // Visor glow on the diamond head — the guardian is watching.
        alive: () => (
          <path
            d="M31 7l6 5-6 5-6-5z"
            fill="currentColor"
            stroke="none"
            className="motion-loop"
            style={{ animation: "visor 4.6s ease-in-out infinite" }}
          />
        ),
      };

    // Angular ears over concentric signal arcs — a fox listening to the noise.
    case "echo":
      return {
        base: (
          <>
            <path d="M14 20L11 8l9 5.5M34 20l3-12-9 5.5" />
            <path d="M14 20c0 6.6 4.5 11 10 11s10-4.4 10-11" />
            {eye(20.5, 22.5, 1.3, alive, 0.4)}
            {eye(27.5, 22.5, 1.3, alive, 0.4)}
            <path d="M24 27.5l-1.6 2.2h3.2z" fill="currentColor" stroke="none" />
          </>
        ),
        // Signal arcs pulsing outward — attention being received.
        alive: () => (
          <g className="motion-loop" style={{ animation: "visor 3.8s ease-in-out infinite" }}>
            <path d="M38 26.5c1.8 2.6 1.8 6.4 0 9M42 24c3 4.2 3 10.8 0 15" opacity="0.55" />
          </g>
        ),
      };

    // A radiant mane ringing a minimal face. The only sigil that emits light.
    case "apex":
      return {
        base: (
          <>
            <circle cx="24" cy="24" r="9" />
            <path d="M24 6v4M24 38v4M6 24h4M38 24h4M11.3 11.3l2.9 2.9M33.8 33.8l2.9 2.9M36.7 11.3l-2.9 2.9M14.2 33.8l-2.9 2.9" />
            {eye(20.5, 22, 1.3, alive, 0.6)}
            {eye(27.5, 22, 1.3, alive, 0.6)}
            <path d="M21 27.5c1.8 1.6 4.2 1.6 6 0" />
          </>
        ),
        alive: () => (
          <circle
            cx="24"
            cy="24"
            r="13.5"
            opacity="0.35"
            strokeDasharray="2 5"
            className="motion-loop"
            style={{ animation: "orbit 30s linear infinite", transformOrigin: "24px 24px" }}
          />
        ),
      };
  }
}

export interface AgentSigilProps extends React.SVGProps<SVGSVGElement> {
  agent: AgentId;
  size?: number;
  /**
   * Enables the idle layer. Reserve it for display sizes — a 12px sigil in a
   * badge does not need to blink, and sixty animated cards is a frame budget
   * spent on nothing.
   */
  alive?: boolean;
}

export function AgentSigil({
  agent,
  size = 24,
  alive = false,
  className,
  ...props
}: AgentSigilProps) {
  const uid = `sigil-${agent}`;
  const parts = PARTS(agent, alive);

  return (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={cn("shrink-0", className)}
      {...props}
    >
      {parts.base}
      {alive && parts.alive?.(uid)}
      {/* Static mane ring for Apex when idle behaviour is off. */}
      {agent === "apex" && !alive && (
        <circle cx="24" cy="24" r="13.5" opacity="0.35" strokeDasharray="2 5" />
      )}
    </svg>
  );
}

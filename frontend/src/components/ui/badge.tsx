import { AgentSigil } from "@/components/brand/agent-sigil";
import { AGENTS, type AgentId } from "@/lib/design/agents";
import { cn } from "@/lib/utils";

/** Neutral badge. Tone maps to semantic colour, never to an agent hue. */
export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: "neutral" | "safe" | "warn" | "danger" | "plasma" | "apex";
  className?: string;
  children: React.ReactNode;
}) {
  const tones = {
    neutral: "border-line bg-elevated/60 text-ink-dim",
    safe: "border-safe/30 bg-safe/10 text-safe",
    warn: "border-warn/30 bg-warn/10 text-warn",
    danger: "border-danger/35 bg-danger/10 text-danger",
    plasma: "border-plasma/30 bg-plasma/10 text-plasma",
    apex: "border-apex/40 bg-apex/10 text-apex",
  } as const;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-chip border px-2 py-0.5 text-label font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Identifies which specialist produced a finding. */
export function AgentBadge({
  agent,
  showSigil = true,
  className,
}: {
  agent: AgentId;
  showSigil?: boolean;
  className?: string;
}) {
  const spec = AGENTS[agent];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-chip border px-2 py-0.5 text-label font-medium",
        className,
      )}
      style={{
        color: spec.hue,
        borderColor: `color-mix(in oklch, ${spec.hue} 35%, transparent)`,
        background: `color-mix(in oklch, ${spec.hue} 10%, transparent)`,
      }}
    >
      {showSigil && <AgentSigil agent={agent} size={12} />}
      {spec.name}
    </span>
  );
}

/**
 * Live status indicator. The ring pulses only when `live` — a static dot for
 * an idle system, so "alive" carries information rather than being decoration.
 */
export function StatusDot({
  live = true,
  tone = "var(--color-safe)",
  className,
}: {
  live?: boolean;
  tone?: string;
  className?: string;
}) {
  return (
    <span className={cn("relative inline-flex size-2", className)} aria-hidden>
      {live && (
        <span
          className="ambient absolute inset-0 rounded-full animate-[pulse-ring_2s_ease-out_infinite]"
          style={{ background: tone }}
        />
      )}
      <span
        className="relative size-2 rounded-full"
        style={{ background: live ? tone : "var(--color-ink-faint)" }}
      />
    </span>
  );
}

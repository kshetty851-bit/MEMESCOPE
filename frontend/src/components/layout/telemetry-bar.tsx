"use client";

import { useEffect, useState } from "react";

import { StatusDot } from "@/components/ui/badge";
import { Label } from "@/components/ui/panel";
import { cn } from "@/lib/utils";

/**
 * MISSION TELEMETRY
 *
 * The station's vital signs, in one horizontally-scrollable strip. Every value
 * is measured, not decorative: latency is a real round trip, the clock is real
 * UTC, health reflects the actual stream state.
 *
 * The clock ticks with a single interval that is cleared on unmount, and only
 * the seconds node re-renders — a full-bar re-render once a second would be a
 * needless 86,400 renders a day.
 */

export interface Telemetry {
  coreStatus: string;
  signalsToday: number;
  eliteGems: number;
  whaleActivity: number;
  healthy: boolean;
  chain?: string;
  latencyMs: number | null;
}

function Cell({
  label,
  children,
  tone,
  className,
}: {
  label: string;
  children: React.ReactNode;
  tone?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex shrink-0 flex-col gap-0.5 px-4 first:pl-0", className)}>
      <Label className="whitespace-nowrap">{label}</Label>
      <span
        data-numeric
        className="whitespace-nowrap text-sm font-medium text-ink"
        style={tone ? { color: tone } : undefined}
      >
        {children}
      </span>
    </div>
  );
}

function UtcClock() {
  const [now, setNow] = useState<string | null>(null);

  useEffect(() => {
    // Rendered client-side only: a server-rendered clock would hydrate stale
    // and flash the wrong time.
    const tick = () => setNow(new Date().toISOString().slice(11, 19));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <span data-numeric className="tabular-nums">
      {now ?? "--:--:--"}
    </span>
  );
}

export function TelemetryBar({
  telemetry,
  className,
}: {
  telemetry: Telemetry;
  className?: string;
}) {
  const {
    coreStatus,
    signalsToday,
    eliteGems,
    whaleActivity,
    healthy,
    chain = "Solana",
    latencyMs,
  } = telemetry;

  return (
    <div
      className={cn(
        // `min-w-0` is load-bearing: as a flex child this bar defaults to
        // `min-width: auto`, so its own content would force the page wider
        // than the viewport and defeat the inner overflow-x-auto on mobile.
        "flex min-w-0 items-center overflow-x-auto rounded-panel border border-line bg-surface/60 px-4 py-2.5 backdrop-blur-xl",
        className,
      )}
      data-panel=""
      role="status"
      aria-label="Mission telemetry"
    >
      <Cell label="AI Core">
        <span className="flex items-center gap-1.5">
          <StatusDot
            live={healthy}
            tone={healthy ? "var(--color-plasma)" : "var(--color-warn)"}
          />
          {coreStatus}
        </span>
      </Cell>

      <span className="h-7 w-px shrink-0 bg-line" aria-hidden />
      <Cell label="Signals today">{signalsToday.toLocaleString()}</Cell>

      <span className="h-7 w-px shrink-0 bg-line" aria-hidden />
      <Cell label="Elite gems" tone={eliteGems > 0 ? "var(--color-apex)" : undefined}>
        {eliteGems}
      </Cell>

      <span className="h-7 w-px shrink-0 bg-line" aria-hidden />
      <Cell
        label="Whale activity"
        tone={whaleActivity > 0 ? "var(--color-titan)" : undefined}
      >
        {whaleActivity > 0 ? `${whaleActivity} active` : "Nominal"}
      </Cell>

      <span className="h-7 w-px shrink-0 bg-line" aria-hidden />
      <Cell
        label="System health"
        tone={healthy ? "var(--color-safe)" : "var(--color-warn)"}
      >
        {healthy ? "Operational" : "Degraded"}
      </Cell>

      <span className="h-7 w-px shrink-0 bg-line" aria-hidden />
      <Cell label="Chain">{chain}</Cell>

      <span className="h-7 w-px shrink-0 bg-line" aria-hidden />
      <Cell
        label="Latency"
        tone={
          latencyMs === null
            ? undefined
            : latencyMs < 400
              ? "var(--color-safe)"
              : latencyMs < 1200
                ? "var(--color-warn)"
                : "var(--color-danger)"
        }
      >
        {latencyMs === null ? "—" : `${latencyMs} ms`}
      </Cell>

      <span className="h-7 w-px shrink-0 bg-line" aria-hidden />
      <Cell label="UTC" className="pr-0">
        <UtcClock />
      </Cell>
    </div>
  );
}

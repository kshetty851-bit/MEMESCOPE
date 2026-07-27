"use client";

import { useEffect, useRef, useState } from "react";

import { Label } from "@/components/ui/panel";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { cn } from "@/lib/utils";

/**
 * A number that counts to its value.
 *
 * Eased with the instrument curve so it decelerates into place rather than
 * ticking linearly — the difference between a readout settling and a slot
 * machine. Skipped entirely under reduced motion, and skipped for large
 * deltas on re-render so a live feed does not re-animate on every tick.
 */
export function AnimatedNumber({
  value,
  // Rounds by default: the tween runs on floats, and without this a counter
  // renders "63.364" mid-flight.
  format = (n) => Math.round(n).toLocaleString(),
  duration = 900,
  className,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(value);
  const frame = useRef<number | undefined>(undefined);
  const from = useRef(value);

  useEffect(() => {
    if (reduced) {
      setDisplay(value);
      return;
    }

    const start = performance.now();
    const origin = from.current;
    const delta = value - origin;
    if (delta === 0) return;

    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      // Expo-out: matches --ease-instrument.
      const eased = 1 - Math.pow(2, -10 * progress);
      setDisplay(origin + delta * (progress === 1 ? 1 : eased));
      if (progress < 1) frame.current = requestAnimationFrame(tick);
      else from.current = value;
    };

    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      from.current = value;
    };
  }, [value, duration, reduced]);

  return (
    <span data-numeric className={className}>
      {format(display)}
    </span>
  );
}

/** Label-over-value block. The workhorse readout of the Command Center. */
export function Metric({
  label,
  value,
  hint,
  tone,
  size = "md",
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <Label>{label}</Label>
      <span
        data-numeric
        className={cn(
          "font-medium text-ink",
          size === "sm" && "text-sm",
          size === "md" && "text-xl",
          size === "lg" && "text-3xl tracking-tight",
        )}
        style={tone ? { color: tone } : undefined}
      >
        {value}
      </span>
      {hint && <span className="text-xs text-ink-faint">{hint}</span>}
    </div>
  );
}

/**
 * Confidence meter. Segmented rather than a smooth bar: discrete ticks read as
 * a measured instrument, and they stop users over-reading a 4% difference.
 */
export function Meter({
  value,
  segments = 12,
  tone = "var(--color-plasma)",
  label,
  className,
}: {
  /** 0–1. */
  value: number;
  segments?: number;
  tone?: string;
  label?: string;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value));
  const filled = Math.round(clamped * segments);

  return (
    <div
      className={cn("flex flex-col gap-1.5", className)}
      role="meter"
      aria-valuenow={Math.round(clamped * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? "Confidence"}
    >
      <div className="flex gap-[3px]" aria-hidden>
        {Array.from({ length: segments }, (_, index) => (
          <span
            key={index}
            className="h-3 flex-1 rounded-[2px] transition-colors duration-300 ease-[var(--ease-precise)]"
            style={{
              background: index < filled ? tone : "var(--color-elevated)",
              boxShadow:
                index < filled ? `0 0 8px color-mix(in oklch, ${tone} 45%, transparent)` : undefined,
            }}
          />
        ))}
      </div>
    </div>
  );
}

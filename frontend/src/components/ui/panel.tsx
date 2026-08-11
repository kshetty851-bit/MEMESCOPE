import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * Panel — the primary surface.
 *
 * One component, three densities. Everything on a screen is a Panel or lives
 * inside one; there is no second card abstraction, which is what keeps the
 * interface feeling machined rather than assembled.
 */

export interface PanelProps extends HTMLAttributes<HTMLDivElement> {
  /** `flush` removes padding for tables and feeds that manage their own. */
  density?: "comfortable" | "compact" | "flush";
  /** Adds the lit top rim. Default on — it is what gives panels their edge. */
  rim?: boolean;
  /** Agent hue applied as a top-edge accent and ambient glow. */
  accent?: string;
  interactive?: boolean;
}

export function Panel({
  density = "comfortable",
  rim = true,
  accent,
  interactive = false,
  className,
  style,
  ...props
}: PanelProps) {
  return (
    <div
      // Retained so screens can still target every surface with one selector.
      data-panel=""
      className={cn(
        // Opaque, and no blur.
        //
        // The translucency and the `backdrop-blur-2xl` existed to separate a
        // panel from the two coloured radial gradients that used to sit on
        // `<body>`. Phase 2 removed those gradients, so the blur was sampling a
        // flat surface and producing the same flat surface — the most expensive
        // effect available, on every panel on screen, for no visible result.
        //
        // Hierarchy now comes from the tonal ramp: canvas 0.135 → surface 0.165
        // is a step the eye reads without help.
        "relative overflow-hidden rounded-lg border border-line bg-surface",
        // One contact shadow to seat the panel. The second, wide shadow read as
        // a drop shadow on a card rather than as a machined edge.
        "shadow-e1",
        rim && "rimlight",
        density === "comfortable" && "p-4",
        density === "compact" && "p-3",
        interactive &&
          "transition-colors duration-[var(--duration-instant)] hover:border-line-strong hover:bg-raised",
        className,
      )}
      style={
        accent ? ({ ...style, "--panel-accent": accent } as React.CSSProperties) : style
      }
      {...props}
    >
      {accent && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px"
          style={{
            background: `linear-gradient(90deg, transparent, ${accent}, transparent)`,
          }}
        />
      )}
      {props.children}
    </div>
  );
}

export function PanelHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("mb-4 flex items-start justify-between gap-4", className)}
      {...props}
    />
  );
}

export function PanelTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn("text-md font-medium tracking-tight text-ink", className)}
      {...props}
    />
  );
}

/** The instrument's voice for field names: small, wide-tracked, quiet. */
export function Label({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn("text-label font-medium uppercase text-ink-3", className)}
      {...props}
    />
  );
}

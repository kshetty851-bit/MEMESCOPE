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
      // `data-panel` lets Command mode strip translucency and blur from every
      // surface with one selector, rather than threading a prop through the tree.
      data-panel=""
      className={cn(
        "relative overflow-hidden rounded-panel border border-line/80 bg-surface/55 backdrop-blur-2xl",
        // Two shadows: a tight contact shadow to seat the panel, and a wide
        // soft one for depth. A single mid shadow reads as a sticker.
        "shadow-[0_1px_0_0_color-mix(in_oklch,var(--color-ink)_6%,transparent)_inset,0_18px_50px_-28px_rgb(0_0_0/0.9)]",
        rim && "rimlight",
        density === "comfortable" && "p-6",
        density === "compact" && "p-4",
        interactive &&
          "transition-[transform,border-color,background-color] duration-200 ease-[var(--ease-instrument)] hover:-translate-y-0.5 hover:border-line-bright hover:bg-elevated/70",
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
      className={cn("text-heading font-medium tracking-tight text-ink", className)}
      {...props}
    />
  );
}

/** The instrument's voice for field names: small, wide-tracked, quiet. */
export function Label({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn("text-label font-medium uppercase text-ink-faint", className)}
      {...props}
    />
  );
}

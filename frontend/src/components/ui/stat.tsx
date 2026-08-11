import type { ReactNode } from "react";

import { Num, type NumTone } from "@/components/ui/num";
import { cn } from "@/lib/utils";

/**
 * STAT — label over value.
 *
 * This shape existed four times before this file: `record`, `wallet` and
 * `strategy-intelligence` each declared a local `Stat`, `lab` declared a local
 * `Metric`, and `real-wallet` declared a `StatusCard`. They agreed on the idea
 * and disagreed on the details — three different value sizes, two different
 * border treatments, and two of them had no dash handling at all.
 *
 * One component, three sizes. The label is always `text-label` caps, the value
 * is always mono, and absence is always a dash because the value goes through
 * `Num`.
 */

export interface StatProps {
  label: string;
  /**
   * Raw figure. Prefer this over `children` — it routes through `Num`, which
   * is what guarantees the dash and the tabular figures.
   */
  value?: string | number | null;
  /** Pre-formatted display text, when the caller has already formatted. */
  display?: string | null;
  /** Anything that is not a single figure: a chip row, a sparkline, prose. */
  children?: ReactNode;
  hint?: ReactNode;
  tone?: NumTone;
  /** Derive tone from sign. `pivot` is 0 for deltas, 1 for multiples. */
  signed?: boolean;
  pivot?: number;
  size?: "sm" | "md" | "lg";
  /** Wraps the stat in a bordered surface. Off inside an existing panel. */
  boxed?: boolean;
  className?: string;
}

const VALUE_SIZE: Record<NonNullable<StatProps["size"]>, string> = {
  sm: "text-sm",
  md: "text-md",
  lg: "text-xl",
};

export function Stat({
  label,
  value,
  display,
  children,
  hint,
  tone = "default",
  signed = false,
  pivot = 0,
  size = "md",
  boxed = false,
  className,
}: StatProps) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-1",
        boxed && "rounded-md border border-line bg-surface px-3 py-2.5",
        className,
      )}
    >
      <span className="text-label font-medium uppercase text-ink-3">{label}</span>

      <span className={cn("truncate font-medium", VALUE_SIZE[size])}>
        {children ?? (
          <Num
            value={value}
            display={display}
            tone={tone}
            signed={signed}
            pivot={pivot}
          />
        )}
      </span>

      {hint ? <span className="text-xs text-ink-3">{hint}</span> : null}
    </div>
  );
}

/**
 * A row of stats on one rule.
 *
 * Dividers rather than gaps: on a dense screen a hairline between figures
 * costs nothing and stops the eye pairing a value with the wrong label.
 */
export function StatRow({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid gap-px overflow-hidden rounded-md border border-line bg-line",
        "[&>*]:bg-surface [&>*]:px-3 [&>*]:py-2.5",
        className,
      )}
    >
      {children}
    </div>
  );
}

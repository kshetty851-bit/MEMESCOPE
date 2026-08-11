import {
  DIRECTION_GLYPH,
  DIRECTION_LABEL,
  directionOf,
  num as parse,
} from "@/lib/design/bands";
import { Absent } from "@/components/ui/num";
import { cn } from "@/lib/utils";

/**
 * DELTA — a change, with its direction stated twice.
 *
 * Green-up / red-down is the most colour-dependent convention in finance and
 * the one that fails hardest: roughly 1 in 12 men has a red-green deficiency,
 * and this product's entire value proposition is read at a glance. So a Delta
 * always carries a glyph as well as a hue, and the glyph is `aria-hidden` with
 * the direction spelled out for assistive tech beside it.
 *
 * The absent case is a dash, never 0% — a token with no reading from a full
 * 24h back has not moved 0%, it has not been measured. `RadarEntry`'s
 * `change_24h_pct` is explicitly nullable for this reason.
 */

export interface DeltaProps {
  /** Decimal string or number. Null renders the dash. */
  value: string | number | null | undefined;
  /** Formats the magnitude. The sign and glyph are added around it. */
  format?: (value: number) => string;
  /**
   * Where "no change" sits. 0 for percentages and absolute deltas, 1 for
   * multiples — `1.0×` is unchanged, which is the Radar's own convention.
   */
  pivot?: number;
  /** Hide the glyph where the surrounding column already states direction. */
  showGlyph?: boolean;
  size?: "sm" | "md";
  className?: string;
}

/** `+12.4%` / `-3.1%`. Percentages arrive already scaled by the backend. */
function defaultFormat(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

export function Delta({
  value,
  format = defaultFormat,
  pivot = 0,
  showGlyph = true,
  size = "sm",
  className,
}: DeltaProps) {
  const parsed = parse(value);
  const direction = directionOf(parsed, pivot);

  if (parsed === null || direction === null) {
    return <Absent className={className} label="change not available" />;
  }

  return (
    <span
      data-numeric
      className={cn(
        "inline-flex items-baseline gap-1 whitespace-nowrap",
        size === "sm" ? "text-xs" : "text-sm",
        direction === "up" && "text-up",
        direction === "down" && "text-down",
        direction === "flat" && "text-ink-2",
        className,
      )}
    >
      {showGlyph ? (
        <span aria-hidden className="text-[0.75em] leading-none">
          {DIRECTION_GLYPH[direction]}
        </span>
      ) : null}
      <span className="sr-only">{DIRECTION_LABEL[direction]} </span>
      {format(parsed)}
    </span>
  );
}

import { riskBandFrom } from "@/lib/design/bands";
import { cn } from "@/lib/utils";

/**
 * RISK — four bands, ordered, never colour alone.
 *
 * The letter beside the swatch is not decoration. Risk is the field in this
 * product most likely to be read under time pressure, on a laptop screen, by
 * someone who may not distinguish the amber band from the orange one. L/M/H/X
 * survives that; a coloured dot does not.
 *
 * Absence is its own rendering. `RadarEntry.risk_band` is null when the sweep
 * had no source, and that is charged to the evidence figure rather than
 * hidden. It must never fall through to `extreme`: on this model an
 * unassessed token would then read as the most dangerous thing on the page.
 */

export interface RiskChipProps {
  /** `low` | `medium` | `high` | `extreme`, cut on the server. */
  band: string | null | undefined;
  /** Server-rendered explanations. Shown as the accessible description. */
  reasons?: string[];
  /** `full` prints the word, `compact` prints the letter only. */
  variant?: "full" | "compact";
  className?: string;
}

export function RiskChip({
  band,
  reasons,
  variant = "full",
  className,
}: RiskChipProps) {
  const resolved = riskBandFrom(band);

  if (!resolved) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-3",
          className,
        )}
      >
        <span
          aria-hidden
          className="size-1.5 shrink-0 rounded-full border border-line-strong"
        />
        {variant === "full" ? "Risk —" : "—"}
        <span className="sr-only">Risk was not assessed for this token</span>
      </span>
    );
  }

  const description = reasons?.length ? reasons.join(". ") : undefined;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-xs",
        className,
      )}
      style={{ color: resolved.color }}
    >
      <span
        aria-hidden
        data-numeric
        className="grid size-4 shrink-0 place-items-center rounded-sm text-[0.625rem] font-medium leading-none"
        style={{
          color: resolved.color,
          background: `color-mix(in oklch, ${resolved.color} 14%, transparent)`,
        }}
      >
        {resolved.letter}
      </span>
      {variant === "full" ? <span>{resolved.label}</span> : null}
      <span className="sr-only">
        {`${resolved.label} risk.${description ? ` ${description}` : ""}`}
      </span>
    </span>
  );
}

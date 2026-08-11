import {
  num as parse,
  scoreBandFromGrade,
  type ScoreBand,
} from "@/lib/design/bands";
import { cn } from "@/lib/utils";
import type { ScoreGrade } from "@/types/score";

/**
 * THE MEMESCOPE SCORE — the product's signature readout.
 *
 * Design constraints this had to satisfy, in order:
 *
 *  - **The band is the message, not the number.** 71 and 68 are the same
 *    decision; 71 and 41 are not. So the band word is never optional, and the
 *    numeral is never the only thing on screen.
 *  - **Not a casino.** No sweeping gauge, no glow, no needle, no gradient
 *    rainbow. The arc is *segmented* — discrete ticks read as a measured
 *    instrument and, more usefully, they stop a reader over-interpreting a
 *    four-point difference that a smooth bar would dramatise.
 *  - **Gold is spent once.** `high_conviction` is the only band that gets the
 *    scarce colour, and it is the only place gold appears in the product.
 *  - **The client holds no opinion on cut points.** The band comes from the
 *    backend's `ScoreGrade`; this component renames `high_conviction` to
 *    `elite` and does nothing else. A second set of thresholds on the client
 *    would eventually disagree with the engine that produced the score.
 *  - **Unscored is not zero.** No score renders a dash and the word "Not
 *    scored". Zero would place a token in the worst band on the strength of a
 *    request that had not finished.
 */

const SEGMENTS = 20;

export interface ScoreBadgeProps {
  /** 0–100, as the decimal string the API sends. */
  score: string | number | null | undefined;
  /** The engine's verdict. Without it there is no band and none is invented. */
  grade: ScoreGrade | null | undefined;
  /**
   * Sustained top-band classification. Renders a hairline marker rather than a
   * second colour — the band already carries the gold.
   */
  isElite?: boolean;
  variant?: "chip" | "dial";
  className?: string;
}

function label(band: ScoreBand | null): string {
  return band?.label ?? "Not scored";
}

/* --------------------------------------------------------------------------
   Chip — for table cells and row headers.
   -------------------------------------------------------------------------- */

function ScoreChip({
  value,
  band,
  isElite,
  className,
}: {
  value: number | null;
  band: ScoreBand | null;
  isElite: boolean;
  className?: string;
}) {
  const text = value === null ? "—" : value.toFixed(0);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 whitespace-nowrap",
        className,
      )}
      title={value === null ? "This token has not been scored." : undefined}
    >
      {/* The band as a 2px rule rather than a filled pill: a pill at this size
          becomes a coloured blob in a column of forty, which is exactly the
          noise a dense table cannot afford. */}
      <span
        aria-hidden
        className="h-4 w-0.5 shrink-0 rounded-full"
        style={{ background: band?.color ?? "var(--color-line)" }}
      />
      <span
        data-numeric
        // When there is no score the dash is decorative: the words beside it
        // already say "Not scored", and announcing both reads as two facts.
        aria-hidden={value === null}
        className={cn("text-sm font-medium tabular-nums", value === null && "text-ink-3")}
        style={value === null ? undefined : { color: band?.color }}
      >
        {text}
      </span>
      <span className="text-xs text-ink-3">{label(band)}</span>
      {isElite ? (
        <span
          className="text-label font-medium uppercase"
          style={{ color: "var(--color-score-elite)" }}
        >
          Elite
        </span>
      ) : null}
      {/* Only the scored case needs a spoken form: "71 Strong" on its own does
          not say what 71 is out of, or what it measures. */}
      {value === null ? null : (
        <span className="sr-only">
          MEMESCOPE score {text} of 100, {label(band)}
        </span>
      )}
    </span>
  );
}

/* --------------------------------------------------------------------------
   Dial — for the token intelligence dossier.
   -------------------------------------------------------------------------- */

function ScoreDial({
  value,
  band,
  isElite,
  className,
}: {
  value: number | null;
  band: ScoreBand | null;
  isElite: boolean;
  className?: string;
}) {
  const filled = value === null ? 0 : Math.round((Math.min(100, Math.max(0, value)) / 100) * SEGMENTS);

  // A 240° sweep with the gap at the bottom. Wide enough to read as a scale,
  // open enough that it never looks like a pie chart.
  const size = 132;
  const centre = size / 2;
  const radius = 54;
  const start = 150;
  const sweep = 240;
  const step = sweep / SEGMENTS;

  return (
    <div
      className={cn("relative inline-flex flex-col items-center", className)}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value ?? undefined}
      aria-valuetext={
        value === null ? "Not scored" : `${value.toFixed(0)} of 100, ${label(band)}`
      }
      aria-label="MEMESCOPE score"
    >
      <svg width={size} height={size * 0.78} viewBox={`0 0 ${size} ${size * 0.78}`} aria-hidden>
        {Array.from({ length: SEGMENTS }, (_, index) => {
          const angle = ((start + index * step + step * 0.15) * Math.PI) / 180;
          const inner = radius - 7;
          const x1 = centre + Math.cos(angle) * inner;
          const y1 = centre + Math.sin(angle) * inner;
          const x2 = centre + Math.cos(angle) * radius;
          const y2 = centre + Math.sin(angle) * radius;
          const on = index < filled;

          return (
            <line
              key={index}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              strokeWidth={3}
              strokeLinecap="round"
              stroke={on ? (band?.color ?? "var(--color-line-strong)") : "var(--color-line)"}
            />
          );
        })}
      </svg>

      <div className="pointer-events-none absolute inset-x-0 top-[30%] flex flex-col items-center">
        <span
          data-numeric
          className={cn(
            "text-xl font-medium tabular-nums leading-none",
            value === null && "text-ink-3",
          )}
          style={value === null ? undefined : { color: band?.color }}
        >
          {value === null ? "—" : value.toFixed(0)}
        </span>
        <span className="mt-1.5 text-label font-medium uppercase text-ink-3">
          {label(band)}
        </span>
        {isElite ? (
          <span
            className="mt-1 text-label font-medium uppercase"
            style={{ color: "var(--color-score-elite)" }}
          >
            Elite
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function ScoreBadge({
  score,
  grade,
  isElite = false,
  variant = "chip",
  className,
}: ScoreBadgeProps) {
  const value = parse(score);
  const band = scoreBandFromGrade(grade);
  const Component = variant === "dial" ? ScoreDial : ScoreChip;

  return (
    <Component value={value} band={band} isElite={isElite} className={className} />
  );
}

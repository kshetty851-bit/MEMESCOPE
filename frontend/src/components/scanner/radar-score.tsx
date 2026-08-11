import { num } from "@/lib/design/bands";
import { CATEGORY_LABEL } from "@/lib/radar";
import { cn } from "@/lib/utils";
import type { RadarCategory } from "@/types/radar";

/**
 * THE MEMESCOPE SCORE, AS THE SCANNER CAN HONESTLY SHOW IT.
 *
 * A finding from building this column, worth stating plainly: the `/radar` list
 * response carries `opportunity_score` and `category`, but **not** the scoring
 * engine's `ScoreGrade`. Grade lives on `/scores/{mint}`, which is per-token —
 * fetching it for fifty rows would be fifty requests to decorate a column.
 *
 * So `ScoreBadge` is deliberately not used here. It maps a backend `ScoreGrade`
 * to a band, and the only way to use it on this screen would be to derive a
 * grade from the raw score on the client — which is precisely the "second,
 * unversioned opinion" every module in this codebase refuses to hold.
 *
 * What is shown instead is what the Radar actually published:
 *
 *   - the score numeral, unmodified;
 *   - a bar whose width **is** the score out of 100 — a direct encoding, with
 *     no cut points invented anywhere;
 *   - the backend's own `category`, which is its qualitative classification.
 *
 * Colour stays scarce. Gold marks `elite` and nothing else. The five-hue
 * category palette this replaces spent a different neon on every category,
 * which made a table of fifty rows read as a chart of nothing.
 */

export function RadarScore({
  score,
  category,
  className,
}: {
  score: string | null | undefined;
  category: RadarCategory | null | undefined;
  className?: string;
}) {
  const value = num(score);
  const isElite = category === "elite";
  const label = category ? (CATEGORY_LABEL[category] ?? null) : null;

  if (value === null) {
    return (
      <span className={cn("inline-flex flex-col gap-1", className)}>
        <span data-numeric className="text-sm text-ink-3">
          <span aria-hidden>—</span>
          <span className="sr-only">Not scored</span>
        </span>
      </span>
    );
  }

  const pct = Math.max(0, Math.min(100, value));

  return (
    <span className={cn("inline-flex min-w-0 flex-col items-end gap-1", className)}>
      <span className="flex items-baseline gap-1.5">
        <span
          data-numeric
          className={cn(
            "text-sm font-medium tabular-nums",
            isElite ? "text-score-elite" : "text-ink",
          )}
        >
          {value.toFixed(0)}
        </span>
        {label ? (
          <span
            className={cn(
              "text-label font-medium uppercase",
              isElite ? "text-score-elite" : "text-ink-3",
            )}
          >
            {label}
          </span>
        ) : null}
      </span>

      {/* The bar is the number, not a band. Width = score/100, no thresholds. */}
      <span
        aria-hidden
        className="h-0.5 w-full min-w-[3rem] overflow-hidden rounded-full bg-line"
      >
        <span
          className={cn(
            "block h-full rounded-full",
            isElite ? "bg-score-elite" : "bg-accent",
          )}
          style={{ width: `${pct}%` }}
        />
      </span>

      <span className="sr-only">
        MEMESCOPE score {value.toFixed(0)} of 100
        {label ? `, category ${label}` : ""}
      </span>
    </span>
  );
}

/**
 * Evidence as four dots.
 *
 * Kept from the card because the reasoning still holds: a percentage beside a
 * score invites the reader to multiply them, and four dots say "how much of the
 * model had data" without pretending to be a second score.
 *
 * `filled: 0` is a measured floor — the model had data for none of its weight.
 * `null` is the different claim that the row was never scored.
 */
export function EvidenceDots({
  evidence,
  className,
}: {
  evidence: string | null | undefined;
  className?: string;
}) {
  const value = num(evidence);
  const filled =
    value === null ? null : value <= 0 ? 0 : value < 25 ? 1 : value < 50 ? 2 : value < 75 ? 3 : 4;

  return (
    <span
      className={cn("inline-flex items-center gap-0.5", className)}
      role="img"
      aria-label={
        filled === null
          ? "Evidence not recorded"
          : `Evidence ${filled} of 4 — ${Math.round(value!)}% of the model had data`
      }
    >
      {[0, 1, 2, 3].map((index) => (
        <span
          key={index}
          aria-hidden
          className={cn(
            "size-1 rounded-full",
            filled !== null && index < filled ? "bg-ink-2" : "bg-line",
          )}
        />
      ))}
    </span>
  );
}

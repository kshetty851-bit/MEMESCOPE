import { num as parse } from "@/lib/design/bands";
import { cn } from "@/lib/utils";

/**
 * NUM — every figure on screen goes through here.
 *
 * Two long-standing product rules were, until now, conventions that each call
 * site had to remember. Measured across the app before this component existed:
 * `data-numeric` appeared 23 times and `tabular-nums` 54, on a screen where
 * every third element is a number. A convention with that hit rate is not a
 * rule, it is a hope.
 *
 * So both rules become structural:
 *
 *  1. **Mono, tabular, slashed-zero.** Columns of figures line up on the
 *     decimal, digits do not jitter as a live value ticks, and 0 cannot be
 *     read as O in a mint address.
 *  2. **An absent figure renders a dash, never a zero.** This is the most
 *     important line in the file. `null` price is not a price of zero, and an
 *     unassessed risk is not a risk of zero — on the risk model, zero is the
 *     *dangerous* end, so inventing it would be the most consequential
 *     possible error. The dash cannot be switched off.
 *
 * Formatting stays the caller's decision — `formatUsd`, `formatPrice`,
 * `formatMultiple` and friends already encode the product's rounding rules and
 * are not duplicated here. This component decides *typography* and *absence*.
 */

export type NumTone = "default" | "up" | "down" | "flat" | "muted" | "accent";

const TONE: Record<NumTone, string> = {
  default: "text-ink",
  up: "text-up",
  down: "text-down",
  flat: "text-ink-2",
  muted: "text-ink-3",
  accent: "text-accent",
};

export interface NumProps {
  /**
   * The raw figure. Decimal strings are expected and preferred — they are what
   * the API sends, and passing the string through means nothing is rounded
   * before `format` sees it.
   *
   * Optional, because some callers only ever hold a formatted string: the paper
   * wallet formats with `usd()`/`pct()` well before render and never keeps the
   * Decimal. Those pass `display` alone — see the presence rules below.
   */
  value?: string | number | null;
  /**
   * Turns the raw figure into display text. Receives the *original* value, not
   * a parsed float, so formatters that need full decimal precision keep it.
   *
   * Only called when the value is present.
   */
  format?: (value: string | number) => string;
  /**
   * Pre-formatted text. Use when the caller already has the display string and
   * the raw value only decides tone and absence.
   */
  display?: string | null;
  tone?: NumTone;
  /**
   * Derive tone from the sign instead of stating it. `pivot` is where "no
   * change" sits — 0 for deltas, 1 for multiples.
   */
  signed?: boolean;
  pivot?: number;
  /** What a screen reader announces in place of "—". */
  absentLabel?: string;
  className?: string;
  title?: string;
}

export function Num({
  value,
  format,
  display,
  tone = "default",
  signed = false,
  pivot = 0,
  absentLabel = "not available",
  className,
  title,
}: NumProps) {
  const parsed = parse(value);

  /*
    WHAT COUNTS AS PRESENT

    Two call shapes, and they decide absence differently:

      <Num value={raw} />                  raw decides — the normal case
      <Num value={raw} display={text} />   raw decides; text is how it reads
      <Num display={text} />               text decides — pre-formatted callers

    The third shape is why `value` is optional. `usd()` returns "$1,234.56";
    parsing that yields NaN, so a caller holding only the formatted string
    cannot supply a meaningful `value`. Demanding one made every figure on the
    paper wallet render as a dash — the rule was right, the input was a lie.

    When `value` IS supplied it still wins outright, including when it is null:
    a caller passing both is asserting the raw figure is the truth, and a stale
    display string must not survive it.
  */
  const displayOnly = value === undefined;
  const present = displayOnly
    ? display !== null && display !== undefined && display !== ""
    : value !== null && value !== "" && parsed !== null;

  // Present-but-unparseable is still an absence for raw callers. A malformed
  // figure is not a figure, and rendering it would put "NaN" in a column of
  // money.
  if (!present) {
    return (
      <span
        data-numeric
        className={cn("text-ink-3", className)}
        title={title}
      >
        <span aria-hidden>—</span>
        <span className="sr-only">{absentLabel}</span>
      </span>
    );
  }

  // `signed` needs a number to compare. A display-only caller has none, so it
  // keeps whatever tone it stated rather than guessing a direction from text.
  let resolved: NumTone = tone;
  if (signed && parsed !== null) {
    resolved = parsed > pivot ? "up" : parsed < pivot ? "down" : "flat";
  }

  const text =
    display ?? (format ? format(value as string | number) : String(value));

  return (
    <span data-numeric className={cn(TONE[resolved], className)} title={title}>
      {text}
    </span>
  );
}

/**
 * The dash on its own, for callers that are not rendering a figure at all —
 * an empty cell in a table, a field with no source.
 *
 * Exported so "absent" has exactly one appearance in the product rather than
 * a mix of "—", "-", "–", "N/A" and empty strings.
 */
export function Absent({
  label = "not available",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <span data-numeric className={cn("text-ink-3", className)}>
      <span aria-hidden>—</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

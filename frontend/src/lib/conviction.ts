/**
 * Conviction language — the words a user reads instead of a number.
 *
 * Phase 12 replaces `92` with `High Conviction` as the primary reading. The
 * number stays available as a secondary detail, because a user who wants to
 * compare two tokens precisely still needs it; it simply stops being the first
 * thing the eye lands on.
 *
 * ## The rule this module must not break
 *
 * Every label here is a **pure lookup from a backend `grade`**. There is no
 * arithmetic, no threshold, and no score comparison anywhere in this file, and
 * a test asserts the mapping is total over `ScoreGrade`.
 *
 * That is not stylistic. `lib/intelligence.ts` was deleted in Phase 4.1 for
 * owning client-side verdicts that could disagree with the engine about the
 * same token, and renaming a band is exactly how that creeps back: the moment
 * this file decides "score >= 85 reads as Very High Conviction", the frontend
 * holds an opinion the backend has never heard of. The engine publishes its
 * bands at `/api/v1/scores/model`; this file only translates them.
 *
 * If a band needs to move, move it in the engine.
 */

import type { ScoreGrade } from "@/types/score";

export type Conviction =
  | "very_high"
  | "high"
  | "building"
  | "watch_carefully"
  | "speculative"
  | "weak";

/**
 * Backend grade to conviction.
 *
 * `very_high` is deliberately absent from this map. It is reserved for Elite
 * certification, which is a separate gate a grade never earns on its own — and
 * which is unreachable in v1 because four of nine signals have no data source.
 * `convictionOf` applies it from the `is_elite` flag, so the top band stays
 * dark until the platform can actually award it.
 */
const GRADE_TO_CONVICTION: Record<ScoreGrade, Conviction> = {
  high_conviction: "high",
  strong: "building",
  watch: "watch_carefully",
  weak: "speculative",
  critical: "weak",
};

export const CONVICTION_LABEL: Record<Conviction, string> = {
  very_high: "Very High Conviction",
  high: "High Conviction",
  building: "Building",
  watch_carefully: "Watch Carefully",
  speculative: "Speculative",
  weak: "Weak",
};

/**
 * What each label means, in the user's terms.
 *
 * Shown behind the "Why?" affordance on every badge. These describe the
 * engine's own bands rather than adding a second opinion about them.
 */
export const CONVICTION_MEANING: Record<Conviction, string> = {
  very_high:
    "Certified Elite: several independent signals agree at a high level and the " +
    "evidence behind them is strong enough to clear the certification gate.",
  high:
    "The strongest band the engine awards on score alone. The signals it can " +
    "read are aligned and none of them is flashing a warning.",
  building:
    "Improving against its own baseline, but not yet at the level the engine " +
    "treats as conviction.",
  watch_carefully:
    "Mixed. Some signals are constructive and others are not, so the engine is " +
    "neither backing it nor dismissing it.",
  speculative:
    "The engine can see little to support this token beyond its existence and " +
    "current market state.",
  weak:
    "Either scoring at the bottom of the range, or vetoed outright by the risk " +
    "gate regardless of how it scores elsewhere.",
};

/** Descending strength. Used for ordering sections and sorting, never for banding. */
export const CONVICTION_ORDER: readonly Conviction[] = [
  "very_high",
  "high",
  "building",
  "watch_carefully",
  "speculative",
  "weak",
] as const;

/**
 * Design-token colour per conviction.
 *
 * Gold (`--color-apex`) appears only on `very_high`, which is the Elite gate —
 * the design system reserves it exclusively for that and a grade never earns it.
 */
export const CONVICTION_TONE: Record<Conviction, string> = {
  very_high: "var(--color-apex)",
  high: "var(--color-safe)",
  building: "var(--color-oracle)",
  watch_carefully: "var(--color-ink-dim)",
  speculative: "var(--color-ink-faint)",
  weak: "var(--color-danger)",
};

/**
 * The conviction for a scored token.
 *
 * `isElite` is the backend's own certification flag, not a threshold applied
 * here. When it is set the token reads as `very_high` whatever its grade says,
 * because Elite is a stricter gate than any single grade.
 */
export function convictionOf(grade: ScoreGrade, isElite = false): Conviction {
  if (isElite) return "very_high";
  return GRADE_TO_CONVICTION[grade];
}

/** The label a user reads. */
export function convictionLabel(grade: ScoreGrade, isElite = false): string {
  return CONVICTION_LABEL[convictionOf(grade, isElite)];
}

/**
 * Rank for ordering, descending strength first.
 *
 * Presentation only — this decides what appears above what on a page, never
 * what band a token belongs to.
 */
export function convictionRank(conviction: Conviction): number {
  return CONVICTION_ORDER.indexOf(conviction);
}

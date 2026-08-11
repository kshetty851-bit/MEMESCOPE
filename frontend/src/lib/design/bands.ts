/**
 * BANDS — the product's two ordered scales, in one place.
 *
 * The MEMESCOPE score and the risk assessment are the two things a reader
 * decides on, and both are *ordered*. Ordered scales fail in a specific way:
 * different screens invent slightly different cut points, and the same token
 * reads "strong" on one page and "watch" on another.
 *
 * So the mapping lives here, it is pure, and it is tested. Nothing derives a
 * band inline.
 *
 * Two rules hold for every band below:
 *
 *  - **Absent is not a band.** A token that was never scored, or whose risk
 *    sweep had no source, returns `null`. It must never fall through to the
 *    worst band — on this model an unassessed risk would render as `extreme`,
 *    which is the most consequential thing in the product to invent.
 *  - **Colour never carries meaning alone.** Every band ships a `letter` and a
 *    `label` so the primitives can print one beside the swatch.
 */

import type { ScoreGrade } from "@/types/score";

/* --------------------------------------------------------------------------
   Score
   -------------------------------------------------------------------------- */

export type ScoreBandId = "critical" | "weak" | "watch" | "strong" | "elite";

export interface ScoreBand {
  id: ScoreBandId;
  /** What a reader sees. Trader language, not engine language. */
  label: string;
  /** CSS custom property carrying this band's colour. */
  color: string;
  /** Rank, ascending. Useful for sorting and for "improved / worsened". */
  rank: number;
}

export const SCORE_BANDS: Record<ScoreBandId, ScoreBand> = {
  critical: { id: "critical", label: "Critical", color: "var(--color-score-critical)", rank: 0 },
  weak: { id: "weak", label: "Weak", color: "var(--color-score-weak)", rank: 1 },
  watch: { id: "watch", label: "Watch", color: "var(--color-score-watch)", rank: 2 },
  strong: { id: "strong", label: "Strong", color: "var(--color-score-strong)", rank: 3 },
  elite: { id: "elite", label: "High conviction", color: "var(--color-score-elite)", rank: 4 },
};

/**
 * The backend's `ScoreGrade` is the authority on which band a token is in.
 *
 * This is a rename, not a re-derivation: the cut points live in the scoring
 * engine and the client must not hold a second opinion about them. The only
 * transformation is `high_conviction` → `elite`, because the token that band
 * spends is the gold one and "elite" is what it is called everywhere else in
 * the product.
 */
export function scoreBandFromGrade(grade: ScoreGrade | null | undefined): ScoreBand | null {
  if (!grade) return null;
  if (grade === "high_conviction") return SCORE_BANDS.elite;
  return SCORE_BANDS[grade] ?? null;
}

/* --------------------------------------------------------------------------
   Risk
   -------------------------------------------------------------------------- */

export type RiskBandId = "low" | "medium" | "high" | "extreme";

export interface RiskBand {
  id: RiskBandId;
  label: string;
  /** Printed beside the swatch so the band survives without colour. */
  letter: string;
  color: string;
  /** Ascending danger. `low` is the safe end. */
  rank: number;
}

export const RISK_BANDS: Record<RiskBandId, RiskBand> = {
  low: { id: "low", label: "Low", letter: "L", color: "var(--color-risk-low)", rank: 0 },
  medium: { id: "medium", label: "Medium", letter: "M", color: "var(--color-risk-medium)", rank: 1 },
  high: { id: "high", label: "High", letter: "H", color: "var(--color-risk-high)", rank: 2 },
  extreme: { id: "extreme", label: "Extreme", letter: "X", color: "var(--color-risk-extreme)", rank: 3 },
};

/**
 * `RadarEntry.risk_band` is cut on the server against published thresholds.
 *
 * Anything the server did not send — including the empty string — is an
 * absence and returns `null`. There is deliberately no fifth "unknown" band:
 * an absence is not a risk level, and giving it a swatch would make it look
 * like one.
 */
export function riskBandFrom(band: string | null | undefined): RiskBand | null {
  if (!band) return null;
  const key = band.toLowerCase() as RiskBandId;
  return RISK_BANDS[key] ?? null;
}

/* --------------------------------------------------------------------------
   Direction
   -------------------------------------------------------------------------- */

export type Direction = "up" | "down" | "flat";

export const DIRECTION_GLYPH: Record<Direction, string> = {
  up: "▲",
  down: "▼",
  flat: "·",
};

export const DIRECTION_COLOR: Record<Direction, string> = {
  up: "var(--color-up)",
  down: "var(--color-down)",
  flat: "var(--color-neutral)",
};

/** Screen-reader wording, so a direction never reaches assistive tech as a glyph. */
export const DIRECTION_LABEL: Record<Direction, string> = {
  up: "up",
  down: "down",
  flat: "unchanged",
};

/**
 * Direction of a change.
 *
 * `null` in, `null` out — a missing reading has no direction, and calling it
 * `flat` would assert that nothing moved, which is a different claim.
 *
 * `pivot` is where "no change" sits: 0 for a percentage or an absolute delta,
 * 1 for a multiple (1.0× is unchanged, which is the convention the Radar's
 * `current_multiple` already uses).
 */
export function directionOf(
  value: number | null | undefined,
  pivot = 0,
): Direction | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  if (value > pivot) return "up";
  if (value < pivot) return "down";
  return "flat";
}

/* --------------------------------------------------------------------------
   Parsing
   -------------------------------------------------------------------------- */

/**
 * Money and scores arrive as decimal **strings** so a JSON float cannot round
 * them on the wire. This is the one sanctioned place to turn one into a number,
 * and the result is only ever used for display or comparison — never stored.
 *
 * An empty string is an absence, not a zero. That distinction is the whole
 * reason this function returns `null` rather than `NaN` or `0`.
 */
export function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

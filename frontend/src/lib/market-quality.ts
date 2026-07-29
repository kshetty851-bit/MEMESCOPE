/**
 * Market quality — is today worth spending research time on?
 *
 * A trader opening the app deserves to know, before reading a single card,
 * whether the market is offering anything. On a poor day the honest answer is
 * "not much", and saying so is more useful than dressing up six mediocre
 * tokens as opportunities.
 *
 * ## What it measures, and what it refuses to
 *
 * Six inputs, each a count over the observed population: how many projects are
 * in the engine's stronger bands, how many are holding above their detection
 * price, how many are deteriorating, median confidence, and how many carry a
 * clone warning.
 *
 * It never reads price direction. A market where everything is up is not
 * automatically a good research day — a broad rally lifts rugs and real
 * projects alike, and the platform's job is to say which is which. Breadth of
 * *quality* is the signal; breadth of *price* is not.
 *
 * ## Determinism
 *
 * Pure. Every band boundary is a named constant, the score is a plain sum of
 * six declared contributions, and `explain()` returns the arithmetic so the
 * verdict can be checked rather than believed.
 */

export type MarketQuality =
  | "very_weak"
  | "weak"
  | "neutral"
  | "healthy"
  | "strong"
  | "exceptional";

export interface MarketInput {
  /** Projects the engine scored in the window. */
  scored: number;
  /** How many sit in the engine's top two bands. */
  strongOrBetter: number;
  /** Radar detections currently at or above their detection price. */
  aboveEntry: number;
  /** Radar detections tracked at all. */
  tracked: number;
  /** Radar detections flagged by Exit Watch at any severity. */
  deteriorating: number;
  /** Median confidence across scored projects, 0–100. */
  medianConfidence: number;
  /** Projects on today's board carrying a moderate or high clone risk. */
  cloneWarnings: number;
}

export interface MarketAssessment {
  quality: MarketQuality;
  /** 0–100. A transparent sum, not a model output. */
  score: number;
  /** The six contributions, so the total can be checked. */
  factors: { label: string; value: string; points: number; of: number }[];
  /** One sentence a user reads instead of the number. */
  summary: string;
}

export const QUALITY_LABEL: Record<MarketQuality, string> = {
  very_weak: "Very Weak",
  weak: "Weak",
  neutral: "Neutral",
  healthy: "Healthy",
  strong: "Strong",
  exceptional: "Exceptional",
};

export const QUALITY_TONE: Record<MarketQuality, string> = {
  very_weak: "var(--color-danger)",
  weak: "var(--color-warn)",
  neutral: "var(--color-ink-dim)",
  healthy: "var(--color-safe)",
  strong: "var(--color-brand-secondary)",
  exceptional: "var(--color-brand-accent)",
};

/** Band floors, ascending. Published on screen. */
const BANDS: { floor: number; quality: MarketQuality }[] = [
  { floor: 80, quality: "exceptional" },
  { floor: 65, quality: "strong" },
  { floor: 50, quality: "healthy" },
  { floor: 35, quality: "neutral" },
  { floor: 20, quality: "weak" },
  { floor: 0, quality: "very_weak" },
];

function share(part: number, whole: number): number {
  return whole > 0 ? part / whole : 0;
}

function points(fraction: number, max: number): number {
  return Math.round(Math.max(0, Math.min(1, fraction)) * max);
}

/**
 * Assess the day.
 *
 * The weights below are **priors, not fitted parameters** — the same posture
 * the scoring engine takes about its own. They are published here and on
 * screen so the claim is checkable.
 */
export function assessMarket(input: MarketInput): MarketAssessment {
  const {
    scored,
    strongOrBetter,
    aboveEntry,
    tracked,
    deteriorating,
    medianConfidence,
    cloneWarnings,
  } = input;

  // Quality breadth carries the most weight: it is the closest thing to "are
  // there real candidates today", which is the question being asked.
  const qualityShare = share(strongOrBetter, scored);
  const qualityPoints = points(qualityShare * 10, 30);

  // Holding above entry, across the tracked record rather than a chosen slice.
  const breadthPoints = points(share(aboveEntry, tracked), 20);

  // Deterioration counts against the day, so a board full of Exit Watch
  // warnings cannot read as healthy.
  const calmPoints = points(1 - share(deteriorating, tracked), 20);

  // Confidence is the platform's own coverage. A day where it knows little is
  // a poor research day whatever the prices did.
  const confidencePoints = points(medianConfidence / 100, 20);

  // Clone pressure. Capped at ten warnings, beyond which the day is simply
  // noisy and further warnings add no information.
  const clonePoints = points(1 - Math.min(cloneWarnings, 10) / 10, 10);

  const score =
    qualityPoints + breadthPoints + calmPoints + confidencePoints + clonePoints;

  const quality = BANDS.find((band) => score >= band.floor)?.quality ?? "very_weak";

  return {
    quality,
    score,
    factors: [
      {
        label: "Quality breadth",
        value: `${strongOrBetter} of ${scored} in the engine's top bands`,
        points: qualityPoints,
        of: 30,
      },
      {
        label: "Holding above entry",
        value: `${aboveEntry} of ${tracked} tracked detections`,
        points: breadthPoints,
        of: 20,
      },
      {
        label: "Absence of deterioration",
        value: `${deteriorating} of ${tracked} flagged by Exit Watch`,
        points: calmPoints,
        of: 20,
      },
      {
        label: "Confidence",
        value: `median ${Math.round(medianConfidence)}% across scored projects`,
        points: confidencePoints,
        of: 20,
      },
      {
        label: "Clone pressure",
        value: `${cloneWarnings} clone warnings on today's board`,
        points: clonePoints,
        of: 10,
      },
    ],
    summary: summarise(quality, strongOrBetter),
  };
}

function summarise(quality: MarketQuality, strongOrBetter: number): string {
  if (strongOrBetter === 0) {
    return (
      "No project reached the engine's stronger bands today. That is a reading, " +
      "not a gap — on a day like this the most valuable thing LETZMOON can do is " +
      "tell you there is little worth your time."
    );
  }

  switch (quality) {
    case "exceptional":
    case "strong":
      return (
        "Several projects are in the engine's stronger bands with confidence to " +
        "match, and few are deteriorating. A day where research time is likely " +
        "to be well spent."
      );
    case "healthy":
      return (
        "A workable day. There are candidates worth investigating, though " +
        "coverage limits how much the platform can say about any of them."
      );
    case "neutral":
      return (
        "Mixed. Some projects qualify, but breadth and confidence are both " +
        "middling — expect to discard more than you keep."
      );
    default:
      return (
        "A poor research day. Few projects qualify, confidence is low, or the " +
        "board is dominated by deterioration and clone warnings."
      );
  }
}

/**
 * Mission status — where a project sits on its own journey.
 *
 * ## Why this is allowed to exist when `lib/intelligence.ts` was deleted
 *
 * That module was deleted in Phase 4.1 for forming a *second opinion about
 * something the engine already judges*: it scored tokens, so it could disagree
 * with the scoring engine about the same token and there was no way to tell
 * which was right.
 *
 * Mission status is orthogonal to that. It never asks "is this good?" — that
 * is the engine's question and the conviction band is its answer. It asks
 * "where is this in its arc?", which nothing on the backend answers, and it
 * answers it from facts the backend supplies: the current multiple, the peak
 * multiple, the detection baseline, the Exit Watch severity and the age.
 *
 * A token can be `Ascent` and `Speculative` at once — climbing, on thin
 * evidence. Those two readings do not compete, which is the test for whether a
 * derived field belongs here.
 *
 * ## Determinism
 *
 * `missionStatus()` is a pure function of its inputs. The rules are ordered,
 * mutually exclusive and total: every input lands in exactly one state, and the
 * first matching rule wins. The thresholds are published on screen through
 * `MISSION_RULE`, so a user can check the classification rather than trust it.
 */

export type MissionState =
  | "recon"
  | "launch_window"
  | "ascent"
  | "orbit"
  | "holding_pattern"
  | "re_entry"
  | "lost_contact";

export interface MissionInput {
  /** Current price ÷ price at detection. */
  currentMultiple: number | null;
  /** Highest observed multiple since detection. Only ever rises. */
  peakMultiple: number | null;
  daysSinceDetection: number;
  /** Exit Watch severity, when assessed. */
  exitSeverity: "clear" | "watch" | "elevated" | null;
  /** The risk gate capped this token outright. */
  hasVeto: boolean;
  /** Observations behind the reading. Too few and no state is honest. */
  observations: number;
}

/** Below this, the platform has not watched long enough to have a view. */
export const MIN_OBSERVATIONS = 12;

/** A project is still "new" for this long after detection. */
export const LAUNCH_WINDOW_DAYS = 1;

/** Within this band of its peak, a project counts as still at its high. */
export const NEAR_PEAK = 0.9;

/** Below this share of peak, the retreat is material rather than noise. */
export const DEEP_DRAWDOWN = 0.5;

export const MISSION_LABEL: Record<MissionState, string> = {
  recon: "Recon",
  launch_window: "Launch Window",
  ascent: "Ascent",
  orbit: "Orbit",
  holding_pattern: "Holding Pattern",
  re_entry: "Re-entry",
  lost_contact: "Lost Contact",
};

/** What the state means, in the user's terms. Shown behind every badge. */
export const MISSION_MEANING: Record<MissionState, string> = {
  recon:
    "Too little observed history for MEMESCOPE to have a view. It is being " +
    "watched, not assessed.",
  launch_window:
    "Detected within the last day and still close to the price it was found " +
    "at. Everything about it is provisional.",
  ascent:
    "Above the price it was detected at and at or near its highest observed " +
    "point. It has not given the move back.",
  orbit:
    "Still above its detection price but off its high. It held some of the " +
    "move rather than round-tripping.",
  holding_pattern:
    "Close to where it was detected, with no material move in either " +
    "direction since.",
  re_entry:
    "Meaningfully below its own peak. What it reached, it has largely " +
    "given back.",
  lost_contact:
    "Down heavily from its peak, vetoed by the risk gate, or flagged at the " +
    "highest Exit Watch severity.",
};

/** The literal rule, published so a classification can be checked. */
export const MISSION_RULE: Record<MissionState, string> = {
  recon: `Fewer than ${MIN_OBSERVATIONS} observations.`,
  launch_window: `Detected less than ${LAUNCH_WINDOW_DAYS} day ago.`,
  ascent: `Above detection price and holding at least ${Math.round(NEAR_PEAK * 100)}% of its peak.`,
  orbit: "Above detection price but below that share of its peak.",
  holding_pattern: "Within a few percent of the detection price.",
  re_entry: `Below detection price, holding more than ${Math.round(DEEP_DRAWDOWN * 100)}% of its peak.`,
  lost_contact: `Vetoed, at elevated Exit Watch, or holding less than ${Math.round(DEEP_DRAWDOWN * 100)}% of its peak.`,
};

/** Tone per state. Not a value judgement — a position on the arc. */
export const MISSION_TONE: Record<MissionState, string> = {
  recon: "var(--color-ink-faint)",
  launch_window: "var(--color-brand-accent)",
  ascent: "var(--color-brand-secondary)",
  orbit: "var(--color-safe)",
  holding_pattern: "var(--color-ink-dim)",
  re_entry: "var(--color-warn)",
  lost_contact: "var(--color-danger)",
};

/**
 * Classify a project's position on its own journey.
 *
 * Rules are evaluated in order and the first match wins, so the sequence below
 * is the specification. Two orderings are deliberate:
 *
 *   * **Lost Contact outranks everything except insufficient data.** A vetoed
 *     or collapsing project must not be able to read as `Ascent` because its
 *     multiple happens to be above 1.
 *   * **Recon outranks Lost Contact.** Without enough observations there is no
 *     basis for either verdict, and declaring a token lost on four data points
 *     would be the platform inventing certainty it does not have.
 */
export function missionStatus(input: MissionInput): MissionState {
  const { currentMultiple, peakMultiple, exitSeverity, hasVeto, observations } = input;

  if (observations < MIN_OBSERVATIONS || currentMultiple === null) {
    return "recon";
  }

  if (hasVeto || exitSeverity === "elevated") {
    return "lost_contact";
  }

  const peak = peakMultiple ?? currentMultiple;
  const heldShareOfPeak = peak > 0 ? currentMultiple / peak : 1;

  if (heldShareOfPeak < DEEP_DRAWDOWN) {
    return "lost_contact";
  }

  if (input.daysSinceDetection < LAUNCH_WINDOW_DAYS) {
    return "launch_window";
  }

  if (currentMultiple >= 1) {
    return heldShareOfPeak >= NEAR_PEAK ? "ascent" : "orbit";
  }

  // Below detection, but only just — nothing has really happened yet.
  if (currentMultiple >= 0.97) {
    return "holding_pattern";
  }

  return "re_entry";
}

/** Descending "how much has gone right", for ordering summaries. */
export const MISSION_ORDER: readonly MissionState[] = [
  "ascent",
  "orbit",
  "launch_window",
  "holding_pattern",
  "recon",
  "re_entry",
  "lost_contact",
] as const;

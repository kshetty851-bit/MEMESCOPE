/**
 * Research priority — where an hour of attention is likely to pay.
 *
 * ## The question this answers, and the one it refuses
 *
 * It answers: *if you have time to investigate three projects today, which
 * three?* It does not answer: *which should you buy?* Those are different
 * questions and only the first is one the platform can honestly take on — it
 * knows nothing about anyone's position, cost basis, risk tolerance or intent.
 *
 * The distinction is load-bearing, not cosmetic. A project can rank Critical
 * because it is **falling apart**: a veto, an elevated Exit Watch or a clone
 * warning on something a user may already hold is among the most valuable
 * things this product can put in front of them. Ranking is about information
 * value, not desirability, and the two genuinely diverge.
 *
 * ## What drives the ranking
 *
 * Four inputs, each a fact the backend supplied:
 *
 *   * **Newness of information.** Something that just changed is worth looking
 *     at; something static was already assessed yesterday.
 *   * **Evidence.** Confidence gates how much a look can even establish.
 *   * **Stakes.** Risk flags raise priority, because unexamined risk is the
 *     expensive kind.
 *   * **Standing.** The engine's own conviction band, used as an input rather
 *     than restated as a verdict.
 *
 * Pure and deterministic; every contribution is returned so the ranking can be
 * checked rather than trusted.
 */

import type { Conviction } from "@/lib/conviction";
import type { MissionState } from "@/lib/mission";

export type ResearchPriority = "critical" | "high" | "medium" | "low";

export interface PriorityInput {
  conviction: Conviction | null;
  mission: MissionState;
  /** 0–100. The platform's own coverage of this token. */
  confidence: number | null;
  /** Material changes observed since the user's last visit. */
  changeCount: number;
  hasVeto: boolean;
  exitSeverity: "clear" | "watch" | "elevated" | null;
  cloneRisk: "none" | "low" | "moderate" | "high" | null;
}

export interface PriorityResult {
  priority: ResearchPriority;
  /** 0–100, a transparent sum. */
  score: number;
  /** Why it ranked here. Each entry is a fact and the points it carried. */
  drivers: { reason: string; points: number }[];
  /** The single sentence answering "why today?". */
  whyToday: string;
}

export const PRIORITY_LABEL: Record<ResearchPriority, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const PRIORITY_TONE: Record<ResearchPriority, string> = {
  critical: "var(--color-danger)",
  high: "var(--color-brand-accent)",
  medium: "var(--color-ink-dim)",
  low: "var(--color-ink-faint)",
};

export const PRIORITY_MEANING: Record<ResearchPriority, string> = {
  critical:
    "Something here needs looking at today — either a risk that could cost " +
    "you, or a change large enough that yesterday's read is stale.",
  high: "Worth investigating before the rest of the board.",
  medium: "Worth a look if time allows.",
  low: "Nothing has changed enough to justify attention today.",
};

const CONVICTION_POINTS: Record<Conviction, number> = {
  very_high: 25,
  high: 22,
  building: 16,
  watch_carefully: 10,
  speculative: 5,
  weak: 2,
};

/**
 * Rank a project for research attention.
 *
 * Risk is scored *above* conviction on purpose. The most expensive thing a
 * user can do is fail to look at something that is deteriorating, so a veto
 * alone is enough to reach Critical regardless of how well the project scores
 * elsewhere.
 */
export function researchPriority(input: PriorityInput): PriorityResult {
  const drivers: { reason: string; points: number }[] = [];
  let score = 0;

  // --- Stakes: unexamined risk is the expensive kind ------------------------
  if (input.hasVeto) {
    score += 40;
    drivers.push({
      reason: "The risk gate vetoed this token, capping its score outright.",
      points: 40,
    });
  }

  if (input.exitSeverity === "elevated") {
    score += 30;
    drivers.push({ reason: "Exit Watch is reporting elevated deterioration.", points: 30 });
  } else if (input.exitSeverity === "watch") {
    score += 15;
    drivers.push({ reason: "Exit Watch has begun reporting deterioration.", points: 15 });
  }

  if (input.cloneRisk === "high") {
    score += 25;
    drivers.push({
      reason: "The name is contested and this token is not the earliest to use it.",
      points: 25,
    });
  } else if (input.cloneRisk === "moderate") {
    score += 10;
    drivers.push({ reason: "Earlier tokens already used this name.", points: 10 });
  }

  // --- Newness: a stale read is worth less than a fresh one -----------------
  if (input.changeCount > 0) {
    const points = Math.min(input.changeCount * 8, 24);
    score += points;
    drivers.push({
      reason: `${input.changeCount} material ${input.changeCount === 1 ? "change" : "changes"} since your last visit.`,
      points,
    });
  }

  // --- Standing: the engine's band as an input, not a restatement -----------
  if (input.conviction) {
    const points = CONVICTION_POINTS[input.conviction];
    score += points;
    drivers.push({ reason: `The engine places this in its ${input.conviction.replace(/_/g, " ")} band.`, points });
  }

  // --- Evidence: a look can only establish what coverage allows -------------
  if (input.confidence !== null) {
    const points = Math.round((input.confidence / 100) * 15);
    score += points;
    drivers.push({ reason: `Confidence of ${Math.round(input.confidence)}% behind that reading.`, points });
  }

  // Mission states that mean "nothing to see yet" pull priority down: there is
  // no point spending an hour on a project the platform has barely observed.
  if (input.mission === "recon") {
    score -= 15;
    drivers.push({ reason: "Too little observed history to investigate usefully.", points: -15 });
  }

  const bounded = Math.max(0, Math.min(100, score));

  return {
    priority: band(bounded, input),
    score: bounded,
    drivers,
    whyToday: whyToday(input),
  };
}

function band(score: number, input: PriorityInput): ResearchPriority {
  // A veto or an elevated warning reaches Critical on its own. Letting a high
  // score elsewhere dilute that would defeat the point of surfacing it.
  if (input.hasVeto || input.exitSeverity === "elevated") return "critical";
  if (score >= 60) return "critical";
  if (score >= 40) return "high";
  if (score >= 22) return "medium";
  return "low";
}

/**
 * One sentence, from observable facts.
 *
 * Ordered by what a user most needs to hear first: risk before opportunity,
 * change before standing. No generic wording and no AI vocabulary — every
 * branch names something that was actually measured.
 */
function whyToday(input: PriorityInput): string {
  if (input.hasVeto) {
    return "The risk gate vetoed this token — its score is capped whatever else it does.";
  }
  if (input.exitSeverity === "elevated") {
    return "Exit Watch moved to elevated: several independent signals are deteriorating at once.";
  }
  if (input.cloneRisk === "high") {
    return "The name is contested and earlier tokens used it first.";
  }
  if (input.exitSeverity === "watch") {
    return "Exit Watch has started reporting deterioration.";
  }
  if (input.changeCount > 0) {
    return `${input.changeCount} material ${input.changeCount === 1 ? "change" : "changes"} since you last looked.`;
  }

  switch (input.mission) {
    case "ascent":
      return "Above its detection price and holding near its highest observed point.";
    case "orbit":
      return "Still above its detection price after coming off its high.";
    case "launch_window":
      return "Detected within the last day — everything about it is still provisional.";
    case "re_entry":
      return "Below its detection price, having given back most of what it reached.";
    case "lost_contact":
      return "Down heavily from its own peak.";
    case "holding_pattern":
      return "Close to where it was detected, with no material move since.";
    default:
      return "Being watched, with too little observed history to assess yet.";
  }
}

/** Descending urgency, for ordering the queue. */
export const PRIORITY_ORDER: readonly ResearchPriority[] = [
  "critical",
  "high",
  "medium",
  "low",
] as const;

export function priorityRank(priority: ResearchPriority): number {
  return PRIORITY_ORDER.indexOf(priority);
}

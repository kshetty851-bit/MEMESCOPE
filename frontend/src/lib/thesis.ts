/**
 * Investment thesis — the case for and against a token, assembled from
 * evidence the backend already issued.
 *
 * ## What this module is allowed to do
 *
 * Group, order and label. Nothing else.
 *
 * Every sentence a user reads here originates on the server:
 * `ScoreReason.message` is rendered by the scoring engine's `explain.py`, the
 * Radar's detection reasons by `radar/explain.py`, Exit Watch's by
 * `exit_signals/explain.py`, and clone risk by `services/identity.py`. This
 * file decides which pile a sentence belongs in — strength, weakness, risk —
 * using the **severity the backend already assigned**, and never by reading a
 * number and forming an opinion about it.
 *
 * That boundary is the whole reason the frontend is trustworthy. Prose hides a
 * threshold far better than a number does, so a "thesis" module is the single
 * most tempting place in the codebase to smuggle one in. It does not happen
 * here: there is no arithmetic in this file.
 *
 * ## What it deliberately does not do
 *
 * It never says buy, sell, hold, target, or moon. It reports what was observed
 * and what the engine concluded, and stops. A user deciding to act is doing
 * something the platform has no view on — it does not know their position,
 * their cost basis, or their intent.
 */

import type { ReasonSeverity, ScoreComponent, ScoreReason, TokenScore } from "@/types/score";

/** Where a piece of evidence belongs in the case. */
export type ThesisSide = "strength" | "weakness" | "risk" | "context";

export interface ThesisPoint {
  /** Stable key for React and for tests. */
  code: string;
  /** Backend-rendered. Display verbatim. */
  message: string;
  side: ThesisSide;
  /** Which division produced it, when the backend said. */
  agent?: string;
}

export interface Thesis {
  /** Why MEMESCOPE surfaced this token at all. */
  appeared: string[];
  strengths: ThesisPoint[];
  weaknesses: ThesisPoint[];
  risks: ThesisPoint[];
  /** Neutral facts that frame the rest — coverage limits, missing signals. */
  context: ThesisPoint[];
  /** Signals the platform declares but cannot collect. Named, never hidden. */
  unavailable: string[];
}

/**
 * Backend severity to which side of the case a reason lands on.
 *
 * The mapping is total over `ReasonSeverity`, so a severity added to the engine
 * cannot silently vanish from the thesis.
 */
const SEVERITY_TO_SIDE: Record<ReasonSeverity, ThesisSide> = {
  positive: "strength",
  caution: "weakness",
  critical: "risk",
  info: "context",
};

/**
 * Human labels for the model's component ids.
 *
 * Presentation only. The ids and their availability both come from the engine;
 * this renames them for reading.
 */
export const COMPONENT_LABEL: Record<string, string> = {
  liquidity_depth: "Liquidity depth",
  momentum: "Momentum",
  trade_flow: "Trade flow",
  valuation_structure: "Valuation structure",
  survival_age: "Survival",
  contract_safety: "Contract safety",
  holder_distribution: "Holder distribution",
  smart_money: "Smart money",
  narrative: "Narrative",
};

export function componentLabel(id: string): string {
  return COMPONENT_LABEL[id] ?? id.replace(/_/g, " ");
}

function pointFrom(reason: ScoreReason): ThesisPoint {
  return {
    code: reason.code,
    message: reason.message,
    side: SEVERITY_TO_SIDE[reason.severity],
    agent: reason.agent,
  };
}

/**
 * Assemble the case for a token.
 *
 * `score` may be null — an unscored token still has a thesis, it is just a
 * short one saying so. `radar` is optional because most tokens are not on the
 * Radar; when present its detection reasons explain why it was surfaced.
 */
export function buildThesis(
  score: TokenScore | null,
  radarReasons?: string[],
): Thesis {
  const thesis: Thesis = {
    appeared: [],
    strengths: [],
    weaknesses: [],
    risks: [],
    context: [],
    unavailable: [],
  };

  // --- Why it appeared ------------------------------------------------------
  // The Radar's own detection reasons are the honest answer when it has them:
  // they are literally the conditions that put the token on the board.
  if (radarReasons?.length) {
    thesis.appeared.push(...radarReasons);
  }

  if (!score) {
    thesis.context.push({
      code: "NOT_SCORED",
      message:
        "The engine has not scored this token yet, so there is no evidence to " +
        "weigh beyond its presence.",
      side: "context",
    });
    return thesis;
  }

  // --- Evidence the engine issued -------------------------------------------
  for (const reason of score.reasons ?? []) {
    const point = pointFrom(reason);
    if (point.side === "strength") thesis.strengths.push(point);
    else if (point.side === "weakness") thesis.weaknesses.push(point);
    else if (point.side === "risk") thesis.risks.push(point);
    else thesis.context.push(point);
  }

  // --- A veto is the loudest thing the engine can say -----------------------
  // Surfaced explicitly rather than left to the reader to infer from a low
  // score: the gate caps the score outright, which is a different statement
  // from "it scored badly".
  if (score.risk?.has_veto) {
    thesis.risks.unshift({
      code: "RISK_VETO",
      message:
        "The risk gate vetoed this token: its score is capped regardless of how " +
        "strong its other signals are.",
      side: "risk",
      agent: "Sentinel",
    });
  }

  // --- Signals that do not exist -------------------------------------------
  // Named individually. A user comparing two tokens deserves to know the same
  // four things are missing from both, rather than reading low confidence as a
  // judgement about this one.
  for (const component of score.components ?? []) {
    if (!component.available) {
      thesis.unavailable.push(componentLabel(component.id));
    }
  }

  return thesis;
}

/**
 * The strongest components the engine could actually read, best first.
 *
 * Ordering by the backend's own `contribution` figure — comparing two numbers
 * the server produced is not a verdict, it is a sort.
 */
export function leadingComponents(
  components: ScoreComponent[] | undefined,
  limit = 3,
): ScoreComponent[] {
  return [...(components ?? [])]
    .filter((component) => component.available)
    .sort((a, b) => Number(b.contribution) - Number(a.contribution))
    .slice(0, limit);
}

/** True when the platform has nothing to say beyond the token existing. */
export function isThesisEmpty(thesis: Thesis): boolean {
  return (
    thesis.appeared.length === 0 &&
    thesis.strengths.length === 0 &&
    thesis.weaknesses.length === 0 &&
    thesis.risks.length === 0
  );
}

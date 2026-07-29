import { GRADE_LABEL, num } from "@/lib/scores";
import type { ScoreComponent, ScoreGrade, ScoreReason, TokenScore } from "@/types/score";

/**
 * SENTINEL — the operator's voice.
 *
 * Sentinel reads what the engine decided and says it in a sentence. It is a
 * narrator, not an analyst.
 *
 * ── THE RULE THAT MAKES THIS SAFE ────────────────────────────────────────────
 * Every statement below is built from exactly three kinds of input:
 *
 *   1. A string the **backend rendered** (`ScoreReason.message`).
 *   2. A **categorical state the backend decided** (`grade`, `has_veto`,
 *      `is_elite`, `status`, `severity`, `available`).
 *   3. **Plain arithmetic** over backend numbers — counts, sums, differences —
 *      stated as the fact it is.
 *
 * What Sentinel must never do is introduce a threshold. The moment a function
 * here says "momentum above 70 is strong", the frontend owns a verdict the
 * engine does not know about, and the two can disagree about the same token.
 * That is precisely the failure `lib/intelligence.ts` was deleted for in Phase
 * 4.1, and this module is a far more tempting place to reintroduce it, because
 * prose hides a threshold better than a number does.
 *
 * So: "no token in this window is graded Strong or better" — a count over
 * backend grades — is allowed. "Market conditions are neutral" is not, because
 * *neutral* is a judgement no backend field returns. Where a verdict is wanted
 * and none exists, Sentinel reports the distribution and lets the reader judge.
 *
 * ── WHY THIS IS SPLIT BY SURFACE ─────────────────────────────────────────────
 * `/scores/top` omits `reasons`, `previous_score` and `components` — a ranking
 * is scanned, not read, and the breakdown is kilobytes per token. So the
 * dashboard can only speak in aggregate, and the token page — which already
 * fetches `/scores/{mint}` — is the only place Sentinel can name a specific
 * signal or a specific change. Neither surface issues a request for Sentinel's
 * benefit; it interprets what the page had already loaded.
 */

/* ------------------------------------------------------------ Aggregate -- */

export interface MarketBrief {
  /** Tokens in the scored window Sentinel can see. */
  scored: number;
  /** Discovered tokens in the live feed, scored or not. */
  discovered: number;
  /** Total scored tokens the backend reports, beyond this window. */
  totalScored: number;
  gradeCounts: Record<ScoreGrade, number>;
  vetoed: number;
  elite: number;
  /** Mean of the backend's own confidence figures, 0–100. */
  meanConfidence: number;
  /** Mean of the backend's own coverage figures, 0–100. */
  meanCoverage: number;
  /** Highest-scoring token in the window, by the backend's score. */
  leader: RankedToken | null;
  /** The window's most dangerous token, by the backend's risk gate. */
  threat: RankedToken | null;
}

export interface RankedToken {
  mint: string;
  label: string;
  score: number;
  grade: ScoreGrade;
  marketRisk: number;
  hasVeto: boolean;
  isElite: boolean;
  confidence: number;
  coverage: number;
}

const EMPTY_GRADES: Record<ScoreGrade, number> = {
  critical: 0,
  weak: 0,
  watch: 0,
  strong: 0,
  high_conviction: 0,
};

/** Grades in ascending order of conviction, so "or better" has a meaning. */
export const GRADE_ORDER: ScoreGrade[] = [
  "critical",
  "weak",
  "watch",
  "strong",
  "high_conviction",
];

/**
 * Fold the cached scoring window into the figures the brief speaks from.
 *
 * `labels` supplies token names from the discovery feed; a mint with no name
 * is shown as a truncated address rather than invented copy.
 */
export function summariseMarket(
  scoresByMint: Map<string, TokenScore>,
  labels: Map<string, string>,
  options: { discovered: number; totalScored: number },
): MarketBrief {
  const gradeCounts = { ...EMPTY_GRADES };
  let vetoed = 0;
  let elite = 0;
  let confidenceTotal = 0;
  let coverageTotal = 0;
  let leader: RankedToken | null = null;
  let threat: RankedToken | null = null;

  for (const [mint, score] of scoresByMint) {
    const ranked = toRanked(mint, score, labels.get(mint));

    gradeCounts[score.grade] = (gradeCounts[score.grade] ?? 0) + 1;
    if (ranked.hasVeto) vetoed += 1;
    if (ranked.isElite) elite += 1;
    confidenceTotal += ranked.confidence;
    coverageTotal += ranked.coverage;

    // The leader is the backend's highest score, not a blend Sentinel invented.
    if (!leader || ranked.score > leader.score) leader = ranked;

    // Danger is ranked the way the engine ranks it: a veto outranks any
    // market_risk figure, because a veto is a categorical decision and
    // market_risk is a magnitude.
    if (!threat || outranksAsThreat(ranked, threat)) threat = ranked;
  }

  const scored = scoresByMint.size;

  return {
    scored,
    discovered: options.discovered,
    totalScored: options.totalScored,
    gradeCounts,
    vetoed,
    elite,
    meanConfidence: scored > 0 ? confidenceTotal / scored : 0,
    meanCoverage: scored > 0 ? coverageTotal / scored : 0,
    leader,
    threat: threat && (threat.hasVeto || threat.marketRisk > 0) ? threat : null,
  };
}

function outranksAsThreat(candidate: RankedToken, current: RankedToken): boolean {
  if (candidate.hasVeto !== current.hasVeto) return candidate.hasVeto;
  return candidate.marketRisk > current.marketRisk;
}

export function toRanked(
  mint: string,
  score: TokenScore,
  label: string | undefined,
): RankedToken {
  return {
    mint,
    label: label ?? `${mint.slice(0, 4)}…${mint.slice(-4)}`,
    score: num(score.score),
    grade: score.grade,
    marketRisk: num(score.risk.market_risk),
    hasVeto: score.risk.has_veto,
    isElite: score.is_elite,
    confidence: num(score.evidence.confidence),
    coverage: num(score.evidence.coverage),
  };
}

/** How many tokens sit at `grade` or above it. */
export function countAtOrAbove(
  counts: Record<ScoreGrade, number>,
  grade: ScoreGrade,
): number {
  const from = GRADE_ORDER.indexOf(grade);
  return GRADE_ORDER.slice(from).reduce((total, key) => total + counts[key], 0);
}

/* -------------------------------------------------------------- Phrasing -- */

export interface Statement {
  id: string;
  text: string;
  tone: "neutral" | "positive" | "caution" | "critical";
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * The mission brief.
 *
 * Every line is a count, a mean or a backend grade. Nothing here decides
 * whether the market is good or bad — it reports what the engine graded and
 * leaves the verdict where it belongs.
 */
export function missionBrief(brief: MarketBrief): Statement[] {
  const lines: Statement[] = [];

  if (brief.scored === 0) {
    return [
      {
        id: "no-window",
        text:
          brief.discovered > 0
            ? `Tracking ${plural(brief.discovered, "discovery", "discoveries")}. None scored yet — the division is still analysing.`
            : "No discoveries in the current window.",
        tone: "neutral",
      },
    ];
  }

  lines.push({
    id: "window",
    text: `Watching ${plural(brief.scored, "scored token")} of ${brief.totalScored.toLocaleString()} the engine has evaluated.`,
    tone: "neutral",
  });

  const promising = countAtOrAbove(brief.gradeCounts, "strong");
  lines.push(
    promising > 0
      ? {
          id: "conviction",
          text: `${plural(promising, "token")} in this window ${promising === 1 ? "is" : "are"} graded Strong or better.`,
          tone: "positive",
        }
      : {
          id: "conviction",
          text: `Nothing in this window is graded Strong or better. ${plural(brief.gradeCounts.watch, "token")} ${brief.gradeCounts.watch === 1 ? "sits" : "sit"} at Watch.`,
          tone: "neutral",
        },
  );

  if (brief.vetoed > 0) {
    lines.push({
      id: "vetoed",
      text: `The risk gate has vetoed ${plural(brief.vetoed, "token")} outright.`,
      tone: "critical",
    });
  }

  // Elite is unreachable until Day 6 by construction. Saying so is the honest
  // move: silence would read as "nothing qualified today" rather than "this
  // verdict cannot currently be reached".
  lines.push(
    brief.elite > 0
      ? {
          id: "elite",
          text: `${plural(brief.elite, "token")} carries Elite certification.`,
          tone: "positive",
        }
      : {
          id: "elite",
          text: "No Elite certifications — the gate needs contract and holder data the platform does not yet collect.",
          tone: "neutral",
        },
  );

  return lines;
}

/**
 * Why confidence reads low.
 *
 * Coverage is the share of the model's weight that could be applied, and
 * confidence is that discounted by how fresh the observation is. Both are
 * backend figures; the only thing added here is the sentence explaining what
 * they mean to someone who has not read the scoring design.
 */
export function coverageBrief(brief: MarketBrief): Statement[] {
  if (brief.scored === 0) return [];

  const coverage = Math.round(brief.meanCoverage);
  const confidence = Math.round(brief.meanConfidence);

  const lines: Statement[] = [
    {
      id: "coverage",
      text: `On average the engine could apply ${coverage}% of its model to these tokens.`,
      tone: "neutral",
    },
  ];

  if (confidence < coverage) {
    lines.push({
      id: "freshness",
      text: `Confidence averages ${confidence}%, below coverage, because observations age between scans.`,
      tone: "neutral",
    });
  } else {
    lines.push({
      id: "confidence",
      text: `Confidence averages ${confidence}%.`,
      tone: "neutral",
    });
  }

  lines.push({
    id: "ceiling",
    text: "Signals with no data source yet are declared and counted against coverage rather than hidden, so a low figure means missing inputs — not a weak token.",
    tone: "neutral",
  });

  return lines;
}

/** The window's leader, phrased from its backend grade and score. */
export function opportunityBrief(brief: MarketBrief): Statement[] {
  const { leader } = brief;
  if (!leader) return [];

  const lines: Statement[] = [
    {
      id: "leader",
      text: `${leader.label} leads the window at ${leader.score.toFixed(1)}, graded ${GRADE_LABEL[leader.grade]}.`,
      tone: leader.grade === "critical" ? "caution" : "positive",
    },
  ];

  // Reporting the leader's own confidence alongside its score stops the number
  // being read as more certain than the evidence behind it.
  lines.push({
    id: "leader-confidence",
    text: `Its confidence is ${Math.round(leader.confidence)}%, from ${Math.round(leader.coverage)}% model coverage.`,
    tone: "neutral",
  });

  return lines;
}

/** The window's most dangerous token, ranked the way the engine ranks danger. */
export function threatBrief(brief: MarketBrief): Statement[] {
  const { threat } = brief;
  if (!threat) {
    return [
      {
        id: "no-threat",
        text: "The risk gate has not flagged anything in this window.",
        tone: "neutral",
      },
    ];
  }

  if (threat.hasVeto) {
    return [
      {
        id: "veto",
        text: `${threat.label} has been vetoed by the risk gate — its score is capped regardless of momentum.`,
        tone: "critical",
      },
    ];
  }

  return [
    {
      id: "risk",
      text: `${threat.label} carries the window's highest market risk at ${threat.marketRisk.toFixed(1)}.`,
      tone: "caution",
    },
  ];
}

/* ------------------------------------------------------- Per-token voice -- */

/**
 * Sentinel's read on one token, for the detail view.
 *
 * This is the only surface where the engine's own `reasons` exist, so it is the
 * only place Sentinel can quote them. They arrive already rendered as English
 * by the backend — the frontend is forbidden from composing these sentences,
 * and this function does not.
 */
export function tokenNarrative(score: TokenScore): Statement[] {
  const lines: Statement[] = [];

  const movement = scoreMovement(score);
  if (movement) lines.push(movement);

  for (const reason of orderedReasons(score.reasons)) {
    lines.push({
      id: `reason-${reason.code}`,
      text: reason.message,
      tone: toneOf(reason.severity),
    });
  }

  const missing = missingSignals(score.components);
  if (missing.length > 0) {
    lines.push({
      id: "missing",
      text: `${missing.length === 1 ? "One signal is" : `${missing.length} signals are`} declared but unavailable: ${missing.join(", ")}. Coverage is reduced accordingly.`,
      tone: "neutral",
    });
  }

  return lines;
}

/**
 * What changed since the previous evaluation.
 *
 * `previous_score` and `last_trigger` are supplied by the backend, so this is a
 * subtraction of two backend numbers — not a trend Sentinel inferred.
 */
export function scoreMovement(score: TokenScore): Statement | null {
  if (score.previous_score === null) return null;

  const current = num(score.score);
  const previous = num(score.previous_score);
  const delta = current - previous;

  if (delta === 0) {
    return {
      id: "movement",
      text: `Unchanged at ${current.toFixed(1)} since the previous evaluation.`,
      tone: "neutral",
    };
  }

  const direction = delta > 0 ? "up" : "down";
  return {
    id: "movement",
    text: `Score moved ${direction} ${Math.abs(delta).toFixed(1)} to ${current.toFixed(1)} since the previous evaluation.`,
    tone: delta > 0 ? "positive" : "caution",
  };
}

/** Severity order, so the most consequential readout is read first. */
const SEVERITY_RANK: Record<ScoreReason["severity"], number> = {
  critical: 0,
  caution: 1,
  positive: 2,
  info: 3,
};

export function orderedReasons(reasons: ScoreReason[]): ScoreReason[] {
  return [...reasons].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]);
}

/** Component ids the engine declared but could not apply, humanised. */
export function missingSignals(components: ScoreComponent[]): string[] {
  return components
    .filter((component) => !component.available)
    .map((component) => component.id.replace(/_/g, " "));
}

export function toneOf(severity: ScoreReason["severity"]): Statement["tone"] {
  if (severity === "critical") return "critical";
  if (severity === "caution") return "caution";
  if (severity === "positive") return "positive";
  return "neutral";
}

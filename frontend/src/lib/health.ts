/**
 * Project health — six plain-language readouts, each able to explain itself.
 *
 * ## The problem this module had to solve
 *
 * A status indicator implies a threshold: something decided that this liquidity
 * is "good" and that one is "thin". If the frontend makes that call it owns a
 * verdict the engine never issued, which is the failure `lib/intelligence.ts`
 * was deleted for in Phase 4.1.
 *
 * So no status here is computed from a number. Each dimension's status is
 * derived from the **severity the backend already attached to that component's
 * own reason codes**. The engine says `LIQUIDITY_THIN` is a `caution`; this
 * module reads that severity and renders a caution. If the engine changes its
 * mind about what counts as thin, the indicator follows automatically and this
 * file does not change.
 *
 * There is no arithmetic in this module and no comparison against any constant.
 *
 * ## Why these six
 *
 * The brief asks for liquidity, momentum, activity, stability, community
 * coverage and risk. Five map onto engine components; risk maps onto the risk
 * gate. Community has no data source at all, and says so rather than rendering
 * an empty bar that reads as "zero".
 */

import type { ReasonSeverity, TokenScore } from "@/types/score";

export type HealthStatus =
  /** The engine read this signal and flagged nothing. */
  | "steady"
  /** The engine read it and raised something constructive. */
  | "improving"
  /** The engine raised a caution. */
  | "watch"
  /** The engine raised something critical, or the risk gate fired. */
  | "concern"
  /** No data source. Not a zero, not a pass. */
  | "not_collected";

export interface HealthDimension {
  id: string;
  label: string;
  status: HealthStatus;
  /** Why it reads that way. Backend sentences where they exist. */
  detail: string;
  /** The engine's own reason messages behind this dimension. */
  evidence: string[];
}

export const HEALTH_STATUS_LABEL: Record<HealthStatus, string> = {
  improving: "Improving",
  steady: "Steady",
  watch: "Watch",
  concern: "Concern",
  not_collected: "Not collected",
};

export const HEALTH_STATUS_TONE: Record<HealthStatus, string> = {
  improving: "var(--color-safe)",
  steady: "var(--color-oracle)",
  watch: "var(--color-warn, var(--color-ink-dim))",
  concern: "var(--color-danger)",
  not_collected: "var(--color-ink-faint)",
};

/** Which engine component backs each readout. */
const DIMENSION_SOURCE: { id: string; label: string; component: string }[] = [
  { id: "liquidity", label: "Liquidity", component: "liquidity_depth" },
  { id: "momentum", label: "Momentum", component: "momentum" },
  { id: "activity", label: "Activity", component: "trade_flow" },
  { id: "stability", label: "Stability", component: "survival_age" },
  { id: "community", label: "Community coverage", component: "narrative" },
];

/** Severity to status. Total over `ReasonSeverity`, so nothing is dropped. */
const SEVERITY_TO_STATUS: Record<ReasonSeverity, HealthStatus> = {
  positive: "improving",
  info: "steady",
  caution: "watch",
  critical: "concern",
};

/** Worst-first, so one critical reason is never masked by three positives. */
const SEVERITY_RANK: Record<ReasonSeverity, number> = {
  critical: 3,
  caution: 2,
  positive: 1,
  info: 0,
};

/**
 * Build the six readouts for a token.
 *
 * An unscored token returns every dimension as `not_collected` — the honest
 * answer, since nothing has been read yet.
 */
export function buildHealth(score: TokenScore | null): HealthDimension[] {
  if (!score) {
    return [
      ...DIMENSION_SOURCE.map(({ id, label }) => ({
        id,
        label,
        status: "not_collected" as const,
        detail: "This token has not been scored yet.",
        evidence: [],
      })),
      {
        id: "risk",
        label: "Risk",
        status: "not_collected" as const,
        detail: "This token has not been scored yet.",
        evidence: [],
      },
    ];
  }

  const reasonsByCode = new Map((score.reasons ?? []).map((r) => [r.code, r]));
  const components = new Map((score.components ?? []).map((c) => [c.id, c]));

  const dimensions: HealthDimension[] = DIMENSION_SOURCE.map(({ id, label, component }) => {
    const source = components.get(component);

    if (!source || !source.available) {
      return {
        id,
        label,
        status: "not_collected" as const,
        detail:
          "MEMESCOPE does not collect this signal yet. It is declared in the " +
          "model and counted against confidence rather than assumed to be fine.",
        evidence: [],
      };
    }

    // The component names its own reason codes; the severities live on the
    // score's reason list. Joining them is a lookup, not a judgement.
    const matched = source.reasons
      .map((code) => reasonsByCode.get(code))
      .filter((r): r is NonNullable<typeof r> => Boolean(r));

    if (matched.length === 0) {
      return {
        id,
        label,
        status: "steady" as const,
        detail: "The engine read this signal and raised nothing about it.",
        evidence: [],
      };
    }

    const worst = matched.reduce((a, b) =>
      SEVERITY_RANK[b.severity] > SEVERITY_RANK[a.severity] ? b : a,
    );

    return {
      id,
      label,
      status: SEVERITY_TO_STATUS[worst.severity],
      detail: worst.message,
      evidence: matched.map((r) => r.message),
    };
  });

  dimensions.push(riskDimension(score));
  return dimensions;
}

function riskDimension(score: TokenScore): HealthDimension {
  const critical = (score.reasons ?? []).filter((r) => r.severity === "critical");
  const cautions = (score.reasons ?? []).filter((r) => r.severity === "caution");

  if (score.risk?.has_veto) {
    return {
      id: "risk",
      label: "Risk",
      status: "concern",
      detail:
        "The risk gate vetoed this token. Its score is capped regardless of how " +
        "strong every other signal is.",
      evidence: critical.map((r) => r.message),
    };
  }

  const firstCritical = critical[0];
  if (firstCritical) {
    return {
      id: "risk",
      label: "Risk",
      status: "concern",
      detail: firstCritical.message,
      evidence: critical.map((r) => r.message),
    };
  }

  const firstCaution = cautions[0];
  if (firstCaution) {
    return {
      id: "risk",
      label: "Risk",
      status: "watch",
      detail: firstCaution.message,
      evidence: cautions.map((r) => r.message),
    };
  }

  return {
    id: "risk",
    label: "Risk",
    status: "steady",
    detail:
      "The risk gate raised nothing. Note that contract safety and holder " +
      "distribution are not collected, so this is a floor rather than a clearance.",
    evidence: [],
  };
}

/** How many readouts the platform could actually populate. */
export function collectedCount(dimensions: HealthDimension[]): number {
  return dimensions.filter((d) => d.status !== "not_collected").length;
}

import { describe, expect, it } from "vitest";

import { buildThesis, componentLabel, isThesisEmpty, leadingComponents } from "@/lib/thesis";
import type { ScoreComponent, ScoreReason, TokenScore } from "@/types/score";

function reason(
  code: string,
  severity: ScoreReason["severity"],
  message = `${code} happened.`,
): ScoreReason {
  return { code, severity, agent: "Oracle", message };
}

function component(id: string, available: boolean, contribution = "0"): ScoreComponent {
  return {
    id,
    agent: "Oracle",
    available,
    score: available ? "70" : null,
    declared_weight: "0.20",
    effective_weight: available ? "0.30" : "0",
    contribution,
    raw: {},
    reasons: [],
  };
}

function score(overrides: Partial<TokenScore> = {}): TokenScore {
  return {
    mint_address: "mint",
    score: "70",
    opportunity_raw: "70",
    grade: "strong",
    is_elite: false,
    evidence: {
      evidence: "45",
      coverage: "45",
      observations: 12,
      freshness: "0.99",
      confidence: "44",
    },
    risk: { market_risk: "10", has_veto: false, deduction: "0" },
    model_version: "v1",
    evaluated_at: "2026-07-29T12:00:00Z",
    latest_snapshot_at: "2026-07-29T12:00:00Z",
    previous_score: null,
    last_trigger: null,
    components: [],
    reasons: [],
    ...overrides,
  } as TokenScore;
}

describe("investment thesis", () => {
  it("sorts backend reasons by the severity the backend assigned", () => {
    const thesis = buildThesis(
      score({
        reasons: [
          reason("MOMENTUM_ACCELERATING", "positive"),
          reason("LIQUIDITY_THIN", "caution"),
          reason("RUG_PATTERN", "critical"),
          reason("COVERAGE_LIMITED", "info"),
        ],
      }),
    );

    expect(thesis.strengths.map((p) => p.code)).toEqual(["MOMENTUM_ACCELERATING"]);
    expect(thesis.weaknesses.map((p) => p.code)).toEqual(["LIQUIDITY_THIN"]);
    expect(thesis.risks.map((p) => p.code)).toEqual(["RUG_PATTERN"]);
    expect(thesis.context.map((p) => p.code)).toEqual(["COVERAGE_LIMITED"]);
  });

  it("carries backend messages through verbatim", () => {
    // The client must never rewrite an engine sentence, or the two can
    // disagree about the same token.
    const thesis = buildThesis(
      score({ reasons: [reason("X", "positive", "Liquidity has grown for six hours.")] }),
    );
    expect(thesis.strengths[0]!.message).toBe("Liquidity has grown for six hours.");
  });

  it("surfaces a veto above every other risk", () => {
    // A veto caps the score outright, which is a different claim from
    // "scored badly", so it must not be left for the reader to infer.
    const thesis = buildThesis(
      score({
        risk: { market_risk: "80", has_veto: true, deduction: "40" },
        reasons: [reason("OTHER_RISK", "critical")],
      }),
    );
    expect(thesis.risks[0]!.code).toBe("RISK_VETO");
    expect(thesis.risks).toHaveLength(2);
  });

  it("names every unavailable signal rather than hiding it", () => {
    const thesis = buildThesis(
      score({
        components: [
          component("liquidity_depth", true),
          component("contract_safety", false),
          component("holder_distribution", false),
          component("smart_money", false),
          component("narrative", false),
        ],
      }),
    );

    expect(thesis.unavailable).toEqual([
      "Contract safety",
      "Holder distribution",
      "Smart money",
      "Narrative",
    ]);
  });

  it("explains an unscored token instead of rendering nothing", () => {
    const thesis = buildThesis(null);
    expect(thesis.context[0]!.code).toBe("NOT_SCORED");
    expect(isThesisEmpty(thesis)).toBe(true);
  });

  it("uses Radar detection reasons to answer why it appeared", () => {
    const thesis = buildThesis(score(), [
      "Liquidity is growing.",
      "Volume is expanding.",
    ]);
    expect(thesis.appeared).toHaveLength(2);
  });

  it("orders leading components by the backend's contribution figure", () => {
    const leading = leadingComponents([
      component("momentum", true, "12.5"),
      component("liquidity_depth", true, "20.1"),
      component("survival_age", true, "3.0"),
      component("contract_safety", false, "99"),
    ]);

    expect(leading.map((c) => c.id)).toEqual([
      "liquidity_depth",
      "momentum",
      "survival_age",
    ]);
  });

  it("never offers an unavailable component as evidence", () => {
    const leading = leadingComponents([component("smart_money", false, "99")]);
    expect(leading).toHaveLength(0);
  });

  it("labels component ids for reading", () => {
    expect(componentLabel("liquidity_depth")).toBe("Liquidity depth");
    // An id the engine adds later still renders readably rather than raw.
    expect(componentLabel("some_new_signal")).toBe("some new signal");
  });

  it("contains no recommendation language anywhere", () => {
    const thesis = buildThesis(
      score({
        risk: { market_risk: "80", has_veto: true, deduction: "40" },
        reasons: [reason("A", "positive"), reason("B", "critical")],
        components: [component("smart_money", false)],
      }),
    );

    const everything = [
      ...thesis.appeared,
      ...thesis.strengths.map((p) => p.message),
      ...thesis.weaknesses.map((p) => p.message),
      ...thesis.risks.map((p) => p.message),
      ...thesis.context.map((p) => p.message),
    ]
      .join(" ")
      .toLowerCase();

    for (const banned of ["buy", "sell", "moon", "target price", "guaranteed", "will rise"]) {
      expect(everything).not.toContain(banned);
    }
  });
});

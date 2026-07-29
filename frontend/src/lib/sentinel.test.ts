import { describe, expect, it } from "vitest";

import {
  countAtOrAbove,
  coverageBrief,
  missingSignals,
  missionBrief,
  opportunityBrief,
  orderedReasons,
  scoreMovement,
  summariseMarket,
  threatBrief,
  tokenNarrative,
} from "@/lib/sentinel";
import type { ScoreGrade, TokenScore } from "@/types/score";

function score(overrides: Partial<TokenScore> = {}): TokenScore {
  return {
    mint_address: "mint",
    score: "50.00",
    opportunity_raw: "50.00",
    grade: "watch",
    is_elite: false,
    evidence: {
      evidence: "45.00",
      coverage: "45.00",
      observations: 10,
      freshness: "0.80",
      confidence: "36.00",
    },
    risk: { market_risk: "0.00", has_veto: false, deduction: "0.00" },
    model_version: "v1",
    evaluated_at: "2026-07-28T16:00:00Z",
    latest_snapshot_at: "2026-07-28T16:00:00Z",
    previous_score: null,
    last_trigger: null,
    components: [],
    reasons: [],
    ...overrides,
  };
}

function windowOf(entries: [string, TokenScore][]) {
  return summariseMarket(new Map(entries), new Map(), {
    discovered: entries.length,
    totalScored: 9999,
  });
}

describe("summariseMarket", () => {
  it("ranks the leader by the backend score, not a blend", () => {
    const brief = windowOf([
      ["a", score({ score: "40.00" })],
      ["b", score({ score: "77.00", grade: "strong" })],
      ["c", score({ score: "61.00" })],
    ]);

    expect(brief.leader?.mint).toBe("b");
    expect(brief.leader?.score).toBe(77);
  });

  it("treats a veto as outranking any market_risk magnitude", () => {
    // A veto is a categorical decision by the gate; market_risk is a
    // magnitude. A high number must never outrank an actual veto.
    const brief = windowOf([
      ["risky", score({ risk: { market_risk: "90.00", has_veto: false, deduction: "0" } })],
      ["vetoed", score({ risk: { market_risk: "10.00", has_veto: true, deduction: "0" } })],
    ]);

    expect(brief.threat?.mint).toBe("vetoed");
  });

  it("reports no threat when the gate has flagged nothing", () => {
    const brief = windowOf([["a", score()]]);

    expect(brief.threat).toBeNull();
    expect(threatBrief(brief).at(0)?.text).toContain("not flagged anything");
  });

  it("falls back to a truncated mint when the feed has no name", () => {
    const brief = windowOf([["8kFboZiKNQ4jC8fyNAiCjm9YGV5qs99Ns7fCchdYpump", score()]]);

    // Never an invented name.
    expect(brief.leader?.label).toBe("8kFb…pump");
  });

  it("averages the backend's own confidence and coverage", () => {
    const brief = windowOf([
      [
        "a",
        score({
          evidence: {
            evidence: "40",
            coverage: "40",
            observations: 1,
            freshness: "1",
            confidence: "30",
          },
        }),
      ],
      [
        "b",
        score({
          evidence: {
            evidence: "60",
            coverage: "60",
            observations: 1,
            freshness: "1",
            confidence: "50",
          },
        }),
      ],
    ]);

    expect(brief.meanCoverage).toBe(50);
    expect(brief.meanConfidence).toBe(40);
  });
});

describe("countAtOrAbove", () => {
  it("counts up the conviction ladder", () => {
    const counts: Record<ScoreGrade, number> = {
      critical: 5,
      weak: 4,
      watch: 3,
      strong: 2,
      high_conviction: 1,
    };

    expect(countAtOrAbove(counts, "strong")).toBe(3);
    expect(countAtOrAbove(counts, "critical")).toBe(15);
  });
});

describe("missionBrief", () => {
  it("says the division is still analysing when nothing is scored", () => {
    const brief = summariseMarket(new Map(), new Map(), {
      discovered: 4,
      totalScored: 0,
    });

    expect(missionBrief(brief).at(0)?.text).toContain("still analysing");
  });

  it("reports the distribution rather than judging the market", () => {
    const brief = windowOf([
      ["a", score({ grade: "weak" })],
      ["b", score({ grade: "watch" })],
    ]);
    const text = missionBrief(brief)
      .map((line) => line.text)
      .join(" ");

    expect(text).toContain("Nothing in this window is graded Strong or better");
    // "Neutral", "bullish" and friends are verdicts no backend field returns.
    expect(text).not.toMatch(/neutral|bullish|bearish|healthy/i);
  });

  it("explains that Elite is unreachable rather than staying silent", () => {
    const brief = windowOf([["a", score()]]);
    const elite = missionBrief(brief).find((line) => line.id === "elite");

    expect(elite?.text).toContain("does not yet collect");
  });

  it("reports a veto count as critical", () => {
    const brief = windowOf([
      ["a", score({ risk: { market_risk: "10", has_veto: true, deduction: "0" } })],
    ]);
    const vetoed = missionBrief(brief).find((line) => line.id === "vetoed");

    expect(vetoed?.tone).toBe("critical");
    expect(vetoed?.text).toContain("1 token");
  });
});

describe("coverageBrief", () => {
  it("attributes the confidence shortfall to ageing observations", () => {
    const brief = windowOf([
      [
        "a",
        score({
          evidence: {
            evidence: "45",
            coverage: "45",
            observations: 5,
            freshness: "0.7",
            confidence: "31",
          },
        }),
      ],
    ]);
    const text = coverageBrief(brief)
      .map((line) => line.text)
      .join(" ");

    expect(text).toContain("45%");
    expect(text).toContain("observations age between scans");
    // The point of the coverage mechanism: low coverage is missing inputs, not
    // a weak token. Saying otherwise would misrepresent the engine.
    expect(text).toContain("not a weak token");
  });

  it("says nothing when there is no window to describe", () => {
    const brief = summariseMarket(new Map(), new Map(), { discovered: 0, totalScored: 0 });

    expect(coverageBrief(brief)).toEqual([]);
  });
});

describe("opportunityBrief", () => {
  it("pairs the leader's score with its confidence", () => {
    const brief = windowOf([["a", score({ score: "83.05", grade: "high_conviction" })]]);
    const text = opportunityBrief(brief)
      .map((line) => line.text)
      .join(" ");

    expect(text).toContain("83.0");
    expect(text).toContain("High Conviction");
    // A headline score without its evidence reads as more certain than it is.
    expect(text).toContain("confidence");
  });
});

describe("scoreMovement", () => {
  it("subtracts two backend numbers", () => {
    const movement = scoreMovement(score({ score: "83.05", previous_score: "80.89" }));

    expect(movement?.text).toContain("up 2.2");
    expect(movement?.tone).toBe("positive");
  });

  it("marks a fall as caution", () => {
    expect(scoreMovement(score({ score: "40.00", previous_score: "55.00" }))?.tone).toBe(
      "caution",
    );
  });

  it("is silent when the backend reports no previous score", () => {
    // Ranking rows always omit it; inventing a delta there would be fiction.
    expect(scoreMovement(score({ previous_score: null }))).toBeNull();
  });
});

describe("tokenNarrative", () => {
  it("quotes the backend's rendered messages verbatim", () => {
    const narrative = tokenNarrative(
      score({
        reasons: [
          {
            code: "mom_up",
            severity: "positive",
            agent: "pulse",
            message: "Momentum is increasing rapidly.",
          },
        ],
      }),
    );

    expect(narrative.map((line) => line.text)).toContain("Momentum is increasing rapidly.");
  });

  it("leads with the most severe readout", () => {
    const narrative = tokenNarrative(
      score({
        reasons: [
          { code: "a", severity: "info", agent: "oracle", message: "Info." },
          { code: "b", severity: "critical", agent: "sentinel", message: "Critical." },
          { code: "c", severity: "positive", agent: "pulse", message: "Positive." },
        ],
      }),
    );

    expect(narrative.at(0)?.text).toBe("Critical.");
    expect(narrative.at(0)?.tone).toBe("critical");
  });

  it("names the signals the engine declared but could not apply", () => {
    const narrative = tokenNarrative(
      score({
        components: [
          {
            id: "momentum",
            agent: "pulse",
            available: true,
            score: "70",
            declared_weight: "0.15",
            effective_weight: "0.23",
            contribution: "16",
            raw: {},
            reasons: [],
          },
          {
            id: "contract_safety",
            agent: "sentinel",
            available: false,
            score: null,
            declared_weight: "0.15",
            effective_weight: "0",
            contribution: "0",
            raw: {},
            reasons: [],
          },
          {
            id: "smart_money",
            agent: "titan",
            available: false,
            score: null,
            declared_weight: "0.05",
            effective_weight: "0",
            contribution: "0",
            raw: {},
            reasons: [],
          },
        ],
      }),
    );
    const missing = narrative.find((line) => line.id === "missing");

    expect(missing?.text).toContain("contract safety");
    expect(missing?.text).toContain("smart money");
    expect(missing?.text).not.toContain("momentum");
  });
});

describe("missingSignals", () => {
  it("returns nothing when every declared signal applied", () => {
    expect(
      missingSignals([
        {
          id: "momentum",
          agent: "pulse",
          available: true,
          score: "70",
          declared_weight: "0.15",
          effective_weight: "0.23",
          contribution: "16",
          raw: {},
          reasons: [],
        },
      ]),
    ).toEqual([]);
  });
});

describe("orderedReasons", () => {
  it("does not mutate the array it was given", () => {
    const reasons = [
      { code: "a", severity: "info" as const, agent: "oracle", message: "Info." },
      { code: "b", severity: "critical" as const, agent: "sentinel", message: "Critical." },
    ];
    orderedReasons(reasons);

    expect(reasons.at(0)?.code).toBe("a");
  });
});

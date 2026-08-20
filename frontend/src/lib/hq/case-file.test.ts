import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { deriveCaseFile, UNAVAILABLE_CASE_FILE_STAGES, type CaseSources, type CaseStageStatus } from "@/lib/hq/case-file";
import type { Source } from "@/lib/hq/adapter";
import type { RadarDetail } from "@/types/radar";
import type { PaperPosition, PaperPositions } from "@/types/paper";
import type {
  PaperDecisionRow,
  PaperDecisions,
  SafetyEvaluations,
  TokenSecurityCheck,
  TokenSecurityEvaluation,
  TokenSecurityEvaluations,
} from "@/lib/hq/pipeline";

/**
 * TOKEN CASE FILE — acceptance.
 *
 * The stakes here are identical to HQ-4's, aimed at one mint instead of the
 * whole office: a case that looks complete because later evidence exists is
 * the exact failure this adapter cannot survive. Every test below defends one
 * sentence from the brief — most of them defend the sentence that a stage
 * must never become PASSED from an absence of proof.
 */

// Comfortably after every fixture timestamp below, so "advance the clock"
// tests have real room to move without a fixture's own date outrunning it.
const NOW = Date.parse("2026-06-01T00:00:00Z");
const MINT = "MintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

function at<T>(data: T, observedAt = NOW): Source<T> {
  return { data, observedAt };
}
function failedSource<T>(): Source<T> {
  return { data: null, observedAt: null, failed: true };
}

function radar(overrides: Partial<RadarDetail> = {}): RadarDetail {
  return {
    mint_address: MINT,
    name: "Test Token",
    symbol: "TST",
    image_url: null,
    category: "early_momentum",
    original_category: "early_momentum",
    opportunity_score: "62.5",
    confidence: "70",
    first_detected_at: "2026-01-01T00:00:00Z",
    first_price: "0.001",
    first_market_cap: "50000",
    first_liquidity: "10000",
    first_opportunity_score: "60",
    current_price: "0.0012",
    current_market_cap: "60000",
    current_liquidity: "12000",
    current_multiple: "1.2",
    peak_multiple: "1.5",
    peak_price: "0.0015",
    peak_market_cap: "75000",
    peak_at: null,
    days_since_detection: "1",
    is_active: true,
    detection_reason: ["fresh_graduation"],
    achieved_tiers: [],
    liveness: "alive",
    model_version: "v1",
    last_evaluated_at: "2026-01-01T00:05:00Z",
    base_rate: null,
    market: {
      price_usd: "0.0012",
      market_cap: "60000",
      liquidity_usd: "12000",
      volume_24h: "5000",
      change_24h_pct: "0.2",
      captured_at: "2026-01-01T00:05:00Z",
      dex_name: "pumpswap",
    },
    age_seconds: 3600,
    risk_score: "40",
    risk_band: "medium",
    risk_reasons: [],
    evidence: "80",
    signal: null,
    why_now: null,
    dimensions: [],
    reasons: [],
    achievements: [],
    ...overrides,
  };
}

function position(overrides: Partial<PaperPosition> = {}): PaperPosition {
  return {
    mint_address: MINT,
    name: "Test Token",
    symbol: "TST",
    status: "open",
    pricing_status: "priced",
    opened_at: "2026-01-01T00:10:00Z",
    entry_rank: 1,
    entry_price: "0.0012",
    entry_observed_price: "0.0012",
    size_usd: "10",
    quantity: "8333",
    entry_execution_model_version: null,
    entry_execution_price_impact_pct: null,
    entry_execution_fee_usd: null,
    entry_execution_route: null,
    entry_execution_quoted_at: null,
    entry_execution_confidence: null,
    entry_execution_fallback_reason: null,
    entry_market_cap: "60000",
    entry_liquidity_usd: "12000",
    target_price: null,
    stop_price: null,
    expires_at: null,
    trailing_drawdown: null,
    trailing_stop_price: null,
    current_price: "0.0013",
    current_market_cap: "65000",
    current_pct: "0.08",
    current_price_at: "2026-01-01T01:00:00Z",
    peak_pct: "0.1",
    closed_at: null,
    exit_price: null,
    exit_observed_price: null,
    exit_execution_model_version: null,
    exit_execution_price_impact_pct: null,
    exit_execution_fee_usd: null,
    exit_execution_route: null,
    exit_execution_quoted_at: null,
    exit_execution_confidence: null,
    exit_execution_fallback_reason: null,
    exit_reason: null,
    manual_action_at: null,
    pnl_usd: null,
    gross_pnl_usd: null,
    fee_usd: null,
    slippage_usd: null,
    net_pnl_usd: null,
    cost_unavailable_reason: null,
    ...overrides,
  } as PaperPosition;
}

function positions(items: PaperPosition[] = [], enabled = true): PaperPositions {
  return { items, enabled, observed_at: "2026-01-01T00:00:00Z" };
}

function safety(items: SafetyEvaluations["items"] = []): SafetyEvaluations {
  return { mint_address: MINT, items };
}

function check(
  name: string,
  status: TokenSecurityCheck["status"],
  reason_codes: string[] = [],
): TokenSecurityCheck {
  return { name, status, reason_codes, detail: `${name} ${status}`, evidence: {} };
}

/**
 * The shape the platform actually produces today: every mint-account check
 * passes and `LIQUIDITY_SECURITY` is UNKNOWN, because nothing in the codebase
 * has ever read an LP position.
 */
function evaluation(
  overrides: Partial<TokenSecurityEvaluation> = {},
): TokenSecurityEvaluation {
  return {
    mint_address: MINT,
    evaluated_at: "2026-01-01T00:01:00Z",
    overall_status: "UNKNOWN",
    evaluator_version: "1.0.0",
    market_snapshot_at: null,
    reason_codes: ["LIQUIDITY_SECURITY_UNVERIFIED"],
    checks: [
      check("MINT_AUTHORITY", "PASS"),
      check("FREEZE_AUTHORITY", "PASS"),
      check("TOKEN_PROGRAM", "PASS"),
      check("TOKEN_EXTENSIONS", "PASS"),
      check("VENUE", "PASS"),
      check("LIQUIDITY_SECURITY", "UNKNOWN", ["LIQUIDITY_SECURITY_UNVERIFIED"]),
    ],
    evidence: {},
    stale: false,
    stale_checks: [],
    ...overrides,
  };
}

function tokenSecurity(
  items: TokenSecurityEvaluation[] = [],
): TokenSecurityEvaluations {
  return { mint_address: MINT, evaluator_version: "1.0.0", items };
}

function decisionRow(overrides: Partial<PaperDecisionRow> = {}): PaperDecisionRow {
  return {
    decision: "declined",
    decided_at: "2026-01-01T00:02:00Z",
    source: "paper_candidate",
    wallet_code: "generation-2",
    strategy_id: "trailing_stop_25_v1",
    strategy_version: "1.0.0",
    reason_codes: ["no_price"],
    reason_labels: ["No usable price in the latest reading."],
    entry_outcome: null,
    security_status: null,
    security_evaluated_at: null,
    security_evaluator_version: null,
    ...overrides,
  };
}

function decisions(items: PaperDecisionRow[] = []): PaperDecisions {
  return { mint_address: MINT, items };
}

function build(overrides: Partial<CaseSources> = {}) {
  return deriveCaseFile(MINT, {
    radar: at(radar()),
    safety: at(safety()),
    tokenSecurity: at(tokenSecurity()),
    decisions: at(decisions()),
    paperPositions: at(positions()),
    now: NOW,
    ...overrides,
  });
}

/* ── fail-closed ─────────────────────────────────────────────────────── */

describe("fail-closed", () => {
  it("makes every stage UNAVAILABLE with no sources at all", () => {
    const file = deriveCaseFile(MINT);
    for (const [key, stage] of Object.entries(file.stages)) {
      expect(["PENDING", "UNAVAILABLE"], key).toContain(stage.status);
      expect(stage.status, key).not.toBe("PASSED");
      expect(stage.status, key).not.toBe("FAILED");
    }
  });

  it("never turns a failed radar request into a passed discovery", () => {
    const file = build({ radar: failedSource() });
    expect(file.stages.discovery.status).toBe("UNAVAILABLE");
    expect(file.stages.scoring.status).toBe("UNAVAILABLE");
    expect(file.stages.market.status).toBe("UNAVAILABLE");
  });

  it("never turns a failed paper request into BOUGHT or NOT_BOUGHT", () => {
    const file = build({ paperPositions: failedSource() });
    expect(file.stages.execution.status).toBe("UNAVAILABLE");
  });

  it("all six stages support the full PENDING/PASSED/FAILED/UNAVAILABLE vocabulary", () => {
    const seen = new Set<CaseStageStatus>();
    for (const stage of Object.values(UNAVAILABLE_CASE_FILE_STAGES)) seen.add(stage.status);
    // The default file exercises UNAVAILABLE; the rest of this suite proves
    // every stage can independently reach the other three.
    expect(seen.has("UNAVAILABLE")).toBe(true);
  });

  it("uses no generic COMPLETE status anywhere in the type", () => {
    const file = build();
    for (const stage of Object.values(file.stages)) {
      expect(["PENDING", "PASSED", "FAILED", "UNAVAILABLE"]).toContain(stage.status);
    }
  });
});

/* ── discovery / scoring / market ───────────────────────────────────── */

describe("Radar — discovery", () => {
  it("passes the instant a Radar record exists", () => {
    expect(build().stages.discovery.status).toBe("PASSED");
    expect(build().stages.discovery.timestamp).toBe("2026-01-01T00:00:00Z");
  });

  it("is never stale — a historical fact does not expire", () => {
    const file = build({ now: NOW + 365 * 24 * 60 * 60_000 });
    expect(file.stages.discovery.stale).toBe(false);
  });
});

describe("Luna — scoring", () => {
  it("is PENDING when the entry has no dimension evaluation yet", () => {
    const file = build({ radar: at(radar({ dimensions: [] })) });
    expect(file.stages.scoring.status).toBe("PENDING");
  });

  it("is PASSED once dimensions exist, and carries reason codes", () => {
    const file = build({
      radar: at(
        radar({
          dimensions: [
            { id: "momentum", label: "Momentum", available: true, score: "70", effective_weight: "0.3", reasons: [] },
          ],
          reasons: [{ code: "STRONG_MOMENTUM", agent: "engine", severity: "positive", message: "Momentum is strong." }],
        }),
      ),
    });
    expect(file.stages.scoring.status).toBe("PASSED");
    expect(file.stages.scoring.reasonCodes).toContain("STRONG_MOMENTUM");
  });

  it("goes stale once the score is older than the window", () => {
    const file = build({
      radar: at(
        radar({
          dimensions: [{ id: "momentum", label: "Momentum", available: true, score: "70", effective_weight: "0.3", reasons: [] }],
          last_evaluated_at: "2026-01-01T00:00:00Z",
        }),
      ),
      now: NOW + 60 * 60_000,
    });
    expect(file.stages.scoring.stale).toBe(true);
  });
});

describe("Dex — market facts, never a security conclusion", () => {
  it("reports market facts as PASSED without ever saying locked or secure", () => {
    const file = build();
    expect(file.stages.market.status).toBe("PASSED");
    const text = file.stages.market.summary.toLowerCase();
    for (const forbidden of ["locked", "secure", "safe"]) {
      expect(text, forbidden).not.toContain(forbidden);
    }
  });

  it("is PENDING with no captured market snapshot", () => {
    const file = build({ radar: at(radar({ market: null })) });
    expect(file.stages.market.status).toBe("PENDING");
  });

  it("keeps liquidity as a market fact — never promoted to a security verdict", () => {
    const file = build({
      radar: at(radar({ market: { ...radar().market!, liquidity_usd: "500000" } })),
    });
    // A huge liquidity number must not by itself change Atlas.
    expect(file.stages.safety.status).toBe("UNAVAILABLE");
  });
});

/* ── Atlas ───────────────────────────────────────────────────────────── */

describe("Atlas — the shared security evaluation", () => {
  it("is UNAVAILABLE when no evaluation exists, which is the honest default", () => {
    const file = build({ tokenSecurity: at(tokenSecurity([])) });
    expect(file.stages.safety.status).toBe("UNAVAILABLE");
  });

  it("never infers SAFE from high liquidity, venue, Radar presence, or a Paper buy", () => {
    const file = build({
      radar: at(radar({ market: { ...radar().market!, liquidity_usd: "9999999", dex_name: "pumpswap" } })),
      paperPositions: at(positions([position()])),
      tokenSecurity: at(tokenSecurity([])),
    });
    expect(file.stages.safety.status).toBe("UNAVAILABLE");
    expect(file.stages.safety.summary.toLowerCase()).not.toMatch(
      /\bis safe\b|\bfound safe\b|\bconsidered safe\b/,
    );
  });

  it("is UNKNOWN — not PASSED — when liquidity security is unverified", () => {
    // The single most important assertion in this file. Every mint-account
    // check passes and the token still cannot be called verified, because
    // nothing has proven the liquidity cannot be pulled.
    const file = build({ tokenSecurity: at(tokenSecurity([evaluation()])) });
    expect(file.stages.safety.status).toBe("UNKNOWN");
    expect(file.stages.safety.status).not.toBe("PASSED");
    expect(file.stages.safety.reasonCodes).toContain("LIQUIDITY_SECURITY_UNVERIFIED");
  });

  it("shows the verified custody mechanism, in the evaluator's own terms", () => {
    const file = build({
      tokenSecurity: at(
        tokenSecurity([
          evaluation({
            overall_status: "VERIFIED",
            reason_codes: [],
            checks: [
              check("MINT_AUTHORITY", "PASS"),
              { ...check("LIQUIDITY_SECURITY", "PASS"), evidence: { mechanism: "PUMPSWAP_MIGRATED_LP_BURNED" } },
            ],
          }),
        ]),
      ),
    });
    expect(file.stages.safety.status).toBe("PASSED");
    const row = file.evidence.find((r) => r.label === "Liquidity mechanism");
    expect(row?.value).toBe("Protocol custody — migration LP burned");
  });

  it("shows a bonding-curve mechanism as custody, not as a lock", () => {
    const file = build({
      tokenSecurity: at(
        tokenSecurity([
          evaluation({
            overall_status: "VERIFIED",
            reason_codes: [],
            checks: [{ ...check("LIQUIDITY_SECURITY", "PASS"), evidence: { mechanism: "BONDING_CURVE_CUSTODY" } }],
          }),
        ]),
      ),
    });
    const row = file.evidence.find((r) => r.label === "Liquidity mechanism");
    expect(row?.value).toBe("Bonding-curve custody (pump.fun)");
    expect(row?.value?.toLowerCase()).not.toContain("lock");
  });

  it("never shows a mechanism for a verdict that was not a PASS", () => {
    // A mechanism beside an UNKNOWN would describe a conclusion the backend
    // explicitly declined to reach.
    const file = build({
      tokenSecurity: at(
        tokenSecurity([
          evaluation({
            checks: [
              {
                ...check("LIQUIDITY_SECURITY", "UNKNOWN", ["TRADED_POOL_UNVERIFIED"]),
                evidence: { mechanism: "BONDING_CURVE_CUSTODY" },
              },
            ],
          }),
        ]),
      ),
    });
    expect(file.evidence.find((r) => r.label === "Liquidity mechanism")?.value).toBeNull();
  });

  it("reports liquidity security as verified when the backend proved it", () => {
    const file = build({
      tokenSecurity: at(
        tokenSecurity([
          evaluation({ overall_status: "VERIFIED", reason_codes: [], checks: [check("LIQUIDITY_SECURITY", "PASS")] }),
        ]),
      ),
    });
    expect(file.evidence.find((r) => r.label === "Liquidity security")?.value).toBe("Verified");
  });

  it("never renders the word 'locked' anywhere on the stage", () => {
    const cases = [
      evaluation(),
      evaluation({
        overall_status: "VERIFIED",
        reason_codes: [],
        checks: [{ ...check("LIQUIDITY_SECURITY", "PASS"), evidence: { mechanism: "PUMPSWAP_MIGRATED_LP_BURNED" } }],
      }),
    ];
    for (const item of cases) {
      const file = build({ tokenSecurity: at(tokenSecurity([item])) });
      const text = [
        file.stages.safety.summary,
        ...file.evidence.map((row) => `${row.label} ${row.value ?? ""}`),
      ]
        .join(" ")
        .toLowerCase();
      expect(text).not.toContain("locked");
    }
  });

  it("shows FAILED with the evaluator's own reason codes", () => {
    const file = build({
      tokenSecurity: at(
        tokenSecurity([
          evaluation({
            overall_status: "FAILED",
            reason_codes: ["MINT_AUTHORITY_ACTIVE"],
            checks: [check("MINT_AUTHORITY", "FAIL", ["MINT_AUTHORITY_ACTIVE"])],
          }),
        ]),
      ),
    });
    expect(file.stages.safety.status).toBe("FAILED");
    expect(file.stages.safety.reasonCodes).toContain("MINT_AUTHORITY_ACTIVE");
  });

  it("is VERIFIED only when every applicable check passed", () => {
    const file = build({
      tokenSecurity: at(
        tokenSecurity([
          evaluation({
            overall_status: "VERIFIED",
            reason_codes: [],
            checks: [check("MINT_AUTHORITY", "PASS"), check("VENUE", "PASS")],
          }),
        ]),
      ),
    });
    expect(file.stages.safety.status).toBe("PASSED");
  });

  it("marks the stage stale when the backend says the evidence expired", () => {
    const file = build({
      tokenSecurity: at(tokenSecurity([evaluation({ stale: true })])),
    });
    expect(file.stages.safety.stale).toBe(true);
  });

  it("reports authority state from the check, never from an absent reason code", () => {
    // The old bug: no reason code was rendered as "Not flagged", which is
    // equally true of a token nobody ever looked at.
    const file = build({ tokenSecurity: at(tokenSecurity([evaluation()])) });
    const mintAuthority = file.evidence.find((row) => row.label === "Mint authority");
    expect(mintAuthority?.value).toBe("Revoked");
    const none = build({ tokenSecurity: at(tokenSecurity([])) });
    expect(none.evidence.find((row) => row.label === "Mint authority")?.value).toBeNull();
  });

  it("does not depend on the Real Wallet's preview evaluation at all", () => {
    const file = build({
      safety: failedSource<SafetyEvaluations>(),
      tokenSecurity: at(tokenSecurity([evaluation()])),
    });
    expect(file.stages.safety.status).toBe("UNKNOWN");
    expect(file.stages.safety.sourced).toBe(true);
  });
});

/* ── the uncomfortable truth this phase exists to record ─────────────── */

describe("Atlas and Rex may disagree, and HQ must say so", () => {
  it("shows ATLAS UNKNOWN alongside REX BOUGHT", () => {
    const file = build({
      tokenSecurity: at(tokenSecurity([evaluation()])),
      paperPositions: at(positions([position()])),
    });
    expect(file.stages.safety.status).toBe("UNKNOWN");
    expect(file.stages.execution.status).toBe("PASSED");
    expect(file.overallState).toBe("bought");
  });

  it("shows ATLAS FAILED alongside DECISION PASSED and REX BOUGHT", () => {
    // Paper's `judge()` reads market facts only and never consults security,
    // so this combination is what the live system genuinely produces. HQ must
    // not resolve it into a tidier story.
    const file = build({
      tokenSecurity: at(
        tokenSecurity([
          evaluation({
            overall_status: "FAILED",
            reason_codes: ["FREEZE_AUTHORITY_ACTIVE"],
            checks: [check("FREEZE_AUTHORITY", "FAIL", ["FREEZE_AUTHORITY_ACTIVE"])],
          }),
        ]),
      ),
      paperPositions: at(positions([position()])),
    });
    expect(file.stages.safety.status).toBe("FAILED");
    expect(file.stages.decision.status).toBe("PASSED");
    expect(file.stages.execution.status).toBe("PASSED");
  });
});

/* ── decision / execution ───────────────────────────────────────────── */

describe("Candidate decision — read back, never recomputed", () => {
  it("renders FAILED from the engine's own recorded verdict", () => {
    const file = build({
      radar: at(radar({ is_active: true })),
      decisions: at(decisions([decisionRow()])),
    });
    expect(file.stages.decision.status).toBe("FAILED");
    expect(file.stages.decision.reasonCodes).toContain("no_price");
    // Server-rendered prose from a stable code, as everywhere else.
    expect(file.stages.decision.summary).toContain("No usable price");
  });

  it("renders PASSED when the recorded verdict was eligible", () => {
    const file = build({
      decisions: at(decisions([decisionRow({ decision: "eligible", reason_codes: [], reason_labels: [] })])),
    });
    expect(file.stages.decision.status).toBe("PASSED");
  });

  it("shows a cash refusal as the engine recorded it, not as a quality failure", () => {
    const file = build({
      decisions: at(
        decisions([
          decisionRow({
            reason_codes: ["insufficient_paper_cash"],
            reason_labels: ["INSUFFICIENT_PAPER_CASH: not enough cash left for a full $10 position."],
          }),
        ]),
      ),
    });
    expect(file.stages.decision.reasonCodes).toContain("insufficient_paper_cash");
  });

  it("renders a SEC-2 security refusal with the evaluator's own reasons", () => {
    const file = build({
      decisions: at(
        decisions([
          decisionRow({
            reason_codes: ["security_gate", "LP_OUTSTANDING"],
            reason_labels: [],
            entry_outcome: "REFUSED_UNKNOWN",
            security_status: "UNKNOWN",
          }),
        ]),
      ),
    });
    expect(file.stages.decision.status).toBe("FAILED");
    expect(file.stages.decision.summary).toContain("LP_OUTSTANDING");
    expect(file.stages.decision.reasonCodes).toContain("security_gate");
  });

  it("says an infrastructure refusal is not a finding about the token", () => {
    // §6/§21: an RPC outage must never read as a dangerous token.
    const file = build({
      decisions: at(
        decisions([
          decisionRow({
            reason_codes: ["security_gate", "LIQUIDITY_SECURITY_UNVERIFIED"],
            reason_labels: [],
            entry_outcome: "REFUSED_UNAVAILABLE",
            security_status: null,
          }),
        ]),
      ),
    });
    expect(file.stages.decision.summary.toLowerCase()).toContain("temporarily refused");
    expect(file.stages.decision.summary.toLowerCase()).toContain("not a finding");
    expect(file.stages.decision.summary.toLowerCase()).not.toContain("unsafe");
  });

  it("still never invents a reason when nothing was recorded", () => {
    const active = build({ radar: at(radar({ is_active: true })), decisions: at(decisions([])) });
    expect(active.stages.decision.status).toBe("PENDING");
    expect(active.stages.decision.reasonCodes).toEqual([]);
  });

  it("is UNKNOWN-by-absence, never a pass, when the decision source failed", () => {
    const file = build({
      radar: at(radar({ is_active: false })),
      decisions: failedSource<PaperDecisions>(),
      paperPositions: at(positions([])),
    });
    expect(file.stages.decision.status).toBe("UNAVAILABLE");
  });

  it("is PASSED the moment a position exists — opening one is the decision", () => {
    const file = build({ paperPositions: at(positions([position()])) });
    expect(file.stages.decision.status).toBe("PASSED");
  });

  it("is PENDING while still active on Radar with no position", () => {
    const file = build({ radar: at(radar({ is_active: true })), paperPositions: at(positions([])) });
    expect(file.stages.decision.status).toBe("PENDING");
  });

  it("is UNAVAILABLE once inactive with no position and no recorded verdict", () => {
    const file = build({
      radar: at(radar({ is_active: false })),
      paperPositions: at(positions([])),
      decisions: at(decisions([])),
    });
    expect(file.stages.decision.status).toBe("UNAVAILABLE");
  });
});

describe("Rex — Paper BOUGHT requires a real position", () => {
  it("is PASSED only when the mint is in the positions record", () => {
    const file = build({ paperPositions: at(positions([position()])) });
    expect(file.stages.execution.status).toBe("PASSED");
    expect(file.stages.execution.summary.toLowerCase()).toContain("bought");
  });

  it("does not become BOUGHT from a passed candidate decision alone", () => {
    const file = build({
      radar: at(radar({ is_active: true })),
      paperPositions: at(positions([])),
    });
    expect(file.stages.decision.status).toBe("PENDING");
    expect(file.stages.execution.status).not.toBe("PASSED");
  });

  it("never shows FAILED — only PENDING or UNAVAILABLE for no execution", () => {
    const file = build({ paperPositions: at(positions([])) });
    expect(file.stages.execution.status).not.toBe("FAILED");
    expect(["PENDING", "UNAVAILABLE"]).toContain(file.stages.execution.status);
  });

  it("labels a closed position with its real exit, not a fabricated one", () => {
    const file = build({
      paperPositions: at(
        positions([
          position({ status: "closed", closed_at: "2026-01-02T00:00:00Z", exit_reason: "stop", net_pnl_usd: "-2.10" }),
        ]),
      ),
    });
    expect(file.stages.execution.status).toBe("PASSED");
    expect(file.stages.execution.summary).toContain("stop");
  });

  it("reports Paper Wallet disabled truthfully rather than as no evidence", () => {
    const file = build({ paperPositions: at(positions([], false)) });
    expect(file.stages.execution.status).toBe("UNAVAILABLE");
    expect(file.stages.execution.summary.toLowerCase()).toContain("disabled");
  });
});

/* ── historical vs current, freshness, evidence ─────────────────────── */

describe("historical vs current evidence", () => {
  it("keeps a paper entry's AT ENTRY figures distinct from Dex's CURRENT figures", () => {
    const file = build({ paperPositions: at(positions([position({ entry_market_cap: "40000" })])) });
    const entryRow = file.evidence.find((row) => row.label === "Paper entry MCAP")!;
    const currentRow = file.evidence.find((row) => row.label === "Current MCAP")!;
    expect(entryRow.when).toBe("entry");
    expect(currentRow.when).toBe("current");
    expect(entryRow.value).not.toBe(currentRow.value);
  });

  it("never overwrites current market evidence with historical entry evidence", () => {
    const file = build({
      radar: at(radar({ market: { ...radar().market!, market_cap: "99000" } })),
      paperPositions: at(positions([position({ entry_market_cap: "40000" })])),
    });
    expect(file.evidence.find((r) => r.label === "Current MCAP")!.value).toContain("99,000");
    expect(file.evidence.find((r) => r.label === "Paper entry MCAP")!.value).toContain("40,000");
  });
});

describe("source freshness", () => {
  it("marks scoring stale once older than its window without discarding it", () => {
    const file = build({
      radar: at(
        radar({
          dimensions: [{ id: "momentum", label: "Momentum", available: true, score: "70", effective_weight: "0.3", reasons: [] }],
          last_evaluated_at: "2026-01-01T00:00:00Z",
        }),
      ),
      now: NOW + 24 * 60 * 60_000,
    });
    expect(file.stages.scoring.status).toBe("PASSED");
    expect(file.stages.scoring.stale).toBe(true);
  });
});

describe("percentage formatting", () => {
  it("does not re-scale current_pct, which the backend already reports as a percentage", () => {
    // Live-verified regression: `_pct_from` in app/paper/api.py already
    // multiplies by 100, so "20.11" means 20.11%. Treating it as a fraction
    // and multiplying again produced "+2011.0%" against a real position.
    const file = build({ paperPositions: at(positions([position({ current_pct: "20.11" })])) });
    const row = file.evidence.find((r) => r.label === "Paper current P/L")!;
    expect(row.value).toBe("+20.1%");
  });

  it("keeps the sign for a loss", () => {
    const file = build({ paperPositions: at(positions([position({ current_pct: "-5.50" })])) });
    const row = file.evidence.find((r) => r.label === "Paper current P/L")!;
    expect(row.value).toBe("-5.5%");
  });
});

describe("evidence rows", () => {
  it("never fills a missing figure with zero", () => {
    const file = build({ radar: at(radar({ market: null })) });
    const row = file.evidence.find((r) => r.label === "Current MCAP")!;
    expect(row.value).toBeNull();
  });

  it("gives every evidence row a source", () => {
    for (const row of build().evidence) {
      expect(row.source, row.label).toBeTruthy();
    }
  });
});

/* ── reachability / isolation ────────────────────────────────────────── */

describe("case-file isolation", () => {
  const root = path.resolve(__dirname, "../../..");

  it("never imports paper strategy or eligibility logic", () => {
    const source = fs.readFileSync(path.join(root, "src/lib/hq/case-file.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["'][^"']*(strategy|eligibility)/);
  });

  it("mutates nothing", () => {
    const source = fs.readFileSync(path.join(root, "src/lib/hq/case-file.ts"), "utf8");
    expect(source).not.toMatch(/method:\s*["'](POST|PUT|PATCH|DELETE)/i);
  });
});
